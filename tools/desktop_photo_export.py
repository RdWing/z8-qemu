# SPDX-License-Identifier: GPL-2.0-or-later
"""Export initialized DCIM photos from a stopped session without changing its card."""
import argparse
from contextlib import contextmanager
import ctypes
import errno
import json
import multiprocessing
import os
from pathlib import Path, PurePosixPath
import signal
import stat
import sys
import tempfile
import time
import unicodedata
from extract_virtual_exfat import extract
from inspect_virtual_exfat import catalog

MAX_FILES = 512
MAX_TOTAL_BYTES = 2 * 1024**3
MAX_FILE_BYTES = 256 * 1024**2


def _flock_type():
    # Native 64-bit struct flock layouts; unsupported hosts fail closed.
    if ctypes.sizeof(ctypes.c_void_p) != 8 or sys.platform not in ('darwin', 'linux'):
        raise ValueError('Photo export requires 64-bit macOS or Linux')
    fields = ([('start', ctypes.c_int64), ('length', ctypes.c_int64),
               ('pid', ctypes.c_int32), ('kind', ctypes.c_short), ('whence', ctypes.c_short)]
              if sys.platform == 'darwin' else
              [('kind', ctypes.c_short), ('whence', ctypes.c_short),
               ('start', ctypes.c_int64), ('length', ctypes.c_int64), ('pid', ctypes.c_int32)])
    class Flock(ctypes.Structure):
        _fields_ = fields
    return Flock


def _identity(path):
    value = path.stat()
    if not stat.S_ISREG(value.st_mode):
        raise ValueError('A regular virtual card file is required')
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


@contextmanager
def card_read_lease(card):
    """QEMU file-posix permission locks, held in the parent of the actual reader.

    QEMU 11.1.1 uses read locks at 100+permission and 200+denied-sharing bits.
    Claim consistent-read; deny write, write-unchanged and resize. Apply before
    checking conflicts, as QEMU does. A separate worker prevents parser closes
    from releasing this process's POSIX locks on the same inode.
    """
    import fcntl
    Flock = _flock_type()
    before = _identity(card)
    with card.open('rb') as source:
        opened = os.fstat(source.fileno())
        if (opened.st_dev, opened.st_ino) != before[:2]:
            raise ValueError('Virtual card changed before export')
        for offset in (100, 201, 202, 203):
            fcntl.lockf(source.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB, 1, offset)
        for offset in (200, 101, 102, 103):
            request = Flock(kind=fcntl.F_WRLCK, whence=os.SEEK_SET, start=offset, length=1)
            response = Flock.from_buffer_copy(fcntl.fcntl(source.fileno(), fcntl.F_GETLK, bytes(request)))
            if response.kind != fcntl.F_UNLCK:
                raise ValueError('Virtual card is in use. Stop its other session before exporting.')
        yield before


def photo_entries(card):
    rows = []
    names = set()
    total = 0
    for row in catalog(card)['files']:
        if row['directory']:
            continue
        name = row['path']
        parts = PurePosixPath(name).parts
        if not parts or parts[0].upper() != 'DCIM' or PurePosixPath(name).suffix.upper() not in ('.NEF', '.JPG', '.JPEG'):
            continue
        if (len(parts) < 3 or name != str(PurePosixPath(name)) or
                any(part in ('.', '..') or '\\' in part or '\0' in part for part in parts)):
            raise ValueError('Unexpected photo path on the virtual card')
        key = unicodedata.normalize('NFC', name).casefold()
        if key in names:
            raise ValueError('Photo paths collide on a case-insensitive destination')
        names.add(key)
        if not 0 < row['bytes'] <= MAX_FILE_BYTES or row['valid_bytes'] != row['bytes']:
            raise ValueError('A photo is incomplete or exceeds the 256 MiB file limit')
        total += row['bytes']
        rows.append(row)
        if len(rows) > MAX_FILES or total > MAX_TOTAL_BYTES:
            raise ValueError('Photo export exceeds the 512-file or 2 GiB limit')
    if not rows:
        raise ValueError('No initialized NEF or JPEG photos were found on this card')
    return rows


class ExportCancelled(Exception):
    pass


def _cancel(*_):
    # selectors may swallow InterruptedError; cancellation must unwind cleanup.
    raise ExportCancelled('Photo export cancelled')


def _copy_worker(card, staging, connection):
    signal.signal(signal.SIGTERM, _cancel)
    try:
        rows = photo_entries(card)
        staging.mkdir()
        for row in rows:
            destination = staging.joinpath(*PurePosixPath(row['path']).parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            extract(card, row['path'], destination, write_receipt=False)
        connection.send(dict(ok=True, count=len(rows), bytes=sum(row['bytes'] for row in rows)))
    except Exception as error:
        connection.send(dict(ok=False, message=str(error)))
    finally:
        connection.close()


def publish_directory(source, destination):
    """Atomic publication that cannot replace an existing file or directory."""
    library = ctypes.CDLL(None, use_errno=True)
    if sys.platform == 'darwin':
        operation = library.renamex_np
        operation.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        result = operation(os.fsencode(source), os.fsencode(destination), 4)  # RENAME_EXCL
    elif sys.platform == 'linux' and hasattr(library, 'renameat2'):
        operation = library.renameat2
        operation.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        result = operation(-100, os.fsencode(source), -100, os.fsencode(destination), 1)  # NOREPLACE
    else:
        raise ValueError('Atomic photo export is unavailable on this host')
    if result:
        code = ctypes.get_errno()
        if code in (errno.EEXIST, errno.ENOTEMPTY):
            raise ValueError('Choose a new folder; photo export never replaces existing files')
        raise OSError(code, os.strerror(code), str(destination))


def export_photos(card, session, destination):
    card, session, destination = Path(card).resolve(), Path(session).resolve(), Path(destination).absolute()
    receipt = json.loads((session/'result.json').read_text())
    recorded = receipt.get('persistent_card', {}).get('path')
    if receipt.get('owned_qemu_stopped') is not True or not recorded or Path(recorded).resolve() != card:
        raise ValueError('Stop the matching card session before exporting photos')
    if destination.exists() or destination.is_symlink() or not destination.parent.is_dir():
        raise ValueError('Choose a new folder in an existing directory')
    context = multiprocessing.get_context('spawn')
    with card_read_lease(card) as before, tempfile.TemporaryDirectory(prefix='.z8-photo-export-', dir=destination.parent) as temp:
        staging = Path(temp)/'photos'
        receiver, sender = context.Pipe(duplex=False)
        worker = context.Process(target=_copy_worker, args=(card, staging, sender))
        try:
            worker.start()
            sender.close()
            deadline = time.monotonic() + 300
            while not receiver.poll(.1):
                if not worker.is_alive() or time.monotonic() >= deadline:
                    raise ValueError('Photo export did not complete. Check the destination before retrying.')
            try:
                response = receiver.recv()
            except EOFError as error:
                raise ValueError('Photo export stopped before its result was confirmed') from error
            worker.join(3)
            if worker.is_alive() or worker.exitcode != 0 or not response.get('ok'):
                raise ValueError(response.get('message', 'Photo export did not complete'))
            if _identity(card) != before:
                raise ValueError('Virtual card changed during export; no photos were published')
            publish_directory(staging, destination)
            return dict(count=response['count'], bytes=response['bytes'], destination=str(destination))
        finally:
            if worker.is_alive():
                worker.terminate(); worker.join(3)
                if worker.is_alive():
                    worker.kill(); worker.join()
            receiver.close(); sender.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--card', type=Path, required=True)
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='New folder for initialized DCIM NEF/JPEG copies')
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, _cancel)
    try:
        print(json.dumps(dict(ok=True, **export_photos(args.card, args.session, args.output))))
    except Exception as error:
        print(json.dumps(dict(ok=False, message=str(error) or 'Photo export did not complete')))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
