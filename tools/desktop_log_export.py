# SPDX-License-Identifier: GPL-2.0-or-later
"""Copy only known diagnostic logs from a stopped session into a private ZIP."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import signal
import stat
import tempfile
import zipfile

MAX_TOTAL_BYTES = 512 * 1024**2
MAX_RECEIPT_BYTES = 64 * 1024**2
LOGS = ('uart-tx.log', 'stderr.log', *(f'ex-usart{i}-tx.log' for i in range(1, 7)), 'plugin-trace.log')


def identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def open_regular(directory, name):
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError('Diagnostic input must be a regular file: ' + name)
        return os.fdopen(fd, 'rb'), info
    except BaseException:
        os.close(fd)
        raise


def export_logs(session, destination):
    session, destination = Path(session).absolute(), Path(destination).absolute()
    if destination.exists() or destination.is_symlink() or not destination.parent.is_dir():
        raise ValueError('Choose a new ZIP file in an existing directory')
    if session.resolve() == destination.parent.resolve() or session.resolve() in destination.parent.resolve().parents:
        raise ValueError('Save the ZIP outside the session folder')
    with ExitStack() as stack:
        directory = os.open(session, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        stack.callback(os.close, directory)
        parent = os.open(session.parent, os.O_RDONLY | os.O_DIRECTORY)
        stack.callback(os.close, parent)
        receipt, receipt_info = open_regular(directory, 'result.json')
        stack.enter_context(receipt)
        if receipt_info.st_size > MAX_RECEIPT_BYTES:
            raise ValueError('Session receipt exceeds the 64 MiB limit')
        record = json.loads(receipt.read(MAX_RECEIPT_BYTES + 1))
        if record.get('owned_qemu_stopped') is not True:
            raise ValueError('Stop the session before exporting diagnostics')
        sources, missing, total = [], [], 0
        for fd, source, name in [(directory, name, name) for name in LOGS] + [(parent, session.name + '.desktop.log', 'launcher.log')]:
            try:
                stream, info = open_regular(fd, source)
            except FileNotFoundError:
                missing.append(name)
                continue
            stack.enter_context(stream)
            total += info.st_size
            if total > MAX_TOTAL_BYTES:
                raise ValueError('Diagnostic logs exceed the 512 MiB input limit')
            sources.append((name, stream, info))
        if not sources:
            raise ValueError('No diagnostic logs were found in this stopped session')
        # Staging and final publication share a filesystem. A hard link publishes
        # the completed ZIP atomically and cannot replace a raced destination.
        with tempfile.TemporaryDirectory(prefix='.z8-log-export-', dir=destination.parent) as temporary:
            staging = Path(temporary) / 'diagnostics.zip'
            rows = []
            with zipfile.ZipFile(staging, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                os.chmod(staging, 0o600)
                for name, stream, info in sources:
                    digest, remaining = hashlib.sha256(), info.st_size
                    member = zipfile.ZipInfo(name)
                    member.compress_type = zipfile.ZIP_DEFLATED
                    member.external_attr = 0o100600 << 16
                    with archive.open(member, 'w', force_zip64=True) as target:
                        while remaining:
                            data = stream.read(min(1024**2, remaining))
                            if not data:
                                raise ValueError('Diagnostic log changed during export: ' + name)
                            target.write(data); digest.update(data); remaining -= len(data)
                    if identity(os.fstat(stream.fileno())) != identity(info):
                        raise ValueError('Diagnostic log changed during export: ' + name)
                    rows.append(dict(name=name, bytes=info.st_size, sha256=digest.hexdigest()))
                if identity(os.fstat(receipt.fileno())) != identity(receipt_info):
                    raise ValueError('Session receipt changed during export')
                archive.writestr('manifest.json', json.dumps(dict(schema=1, classification='private diagnostic logs; review before sharing',
                    files=rows, missing=missing), indent=2) + '\n')
            if any(identity(os.fstat(stream.fileno())) != identity(info) for _,stream,info in sources):
                raise ValueError('Diagnostic logs changed before publication')
            if identity(os.fstat(receipt.fileno())) != identity(receipt_info):
                raise ValueError('Session receipt changed before publication')
            os.link(staging, destination, follow_symlinks=False)
        return dict(count=len(rows), bytes=total, destination=str(destination))


def cancelled(*_):
    raise InterruptedError('Diagnostic export cancelled')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    signal.signal(signal.SIGTERM, cancelled)
    try:
        print(json.dumps(dict(ok=True, **export_logs(args.session, args.output))))
    except Exception as error:
        print(json.dumps(dict(ok=False, message=str(error) or 'Diagnostic export did not complete')))
        raise SystemExit(1)


if __name__ == '__main__':
    main()
