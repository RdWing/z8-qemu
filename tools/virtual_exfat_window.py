# SPDX-License-Identifier: GPL-2.0-or-later
"""Read-only exFAT window, either an extracted volume or one MBR partition."""
from pathlib import Path
import struct


def window(path):
    path=Path(path)
    if not path.is_file():raise ValueError('Regular virtual card/volume file required')
    size=path.stat().st_size
    with path.open('rb') as source:
        boot=source.read(512)
        if len(boot)!=512:raise ValueError('Short volume header')
        if boot[3:11]==b'EXFAT   ':return 0,size
        if boot[510:]!=b'\x55\xaa':raise ValueError('No exFAT volume or MBR')
        entries=[boot[446+k*16:462+k*16] for k in range(4)]
        present=[entry for entry in entries if any(entry)]
        if len(present)!=1 or present[0][4]!=7:raise ValueError('Exactly one generated exFAT partition required')
        start,sectors=struct.unpack_from('<II',present[0],8)
        offset,length=start*512,sectors*512
        if offset<512 or length<512 or offset+length>size:raise ValueError('Partition exceeds regular card')
        source.seek(offset);boot=source.read(512)
        if boot[3:11]!=b'EXFAT   ':raise ValueError('Partition is not exFAT')
    return offset,length


def fsck_private_card(path):
    """Create a temporary read-only loop view of a stopped, owned regular file.

    No filesystem is mounted and no disk device is formatted or repaired.
    Kernel loop ownership, offset and read-only status are checked before fsck.
    """
    import json
    import os
    import subprocess
    import re
    root=Path(os.environ['WL_ZR_WORK']).resolve()/'runs'
    path=Path(path).resolve()
    if (os.name=='nt' or os.environ.get('WSL_DISTRO_NAME')=='ubuntu-noble') or not path.is_relative_to(root):
        raise ValueError('Owned Nikon run file required')
    if not path.is_file():raise ValueError('Owned regular card required')
    if path.name!='capture-card.raw':
        # A declared lossless private card view resolves inside its run mount.
        # Authenticate the symlink and recorded generated-base identity rather
        # than allowing arbitrary regular files or physical block devices.
        run=path.parent.parent
        receipt=run/'card-service.json'
        if path.name!='card.raw' or path.parent.name!='card-mount' or not receipt.is_file():
            raise ValueError('Owned generated card or declared view required')
        service=json.loads(receipt.read_text())
        if (Path(service['card']).absolute()!=run/'capture-card.raw' or
            Path(service['card']).resolve()!=path or Path(service['mount']).resolve()!=path.parent or
            Path(service['base']).resolve()!=run/'capture-card.initial.raw' or
            not Path(service['base']).is_file() or not service.get('lossless') or
            path.stat().st_size!=service['guest_card_bytes']):
            raise ValueError('Declared virtual card identity mismatch')
    for process in Path('/proc').glob('[0-9]*/fd/*'):
        try:target=process.resolve()
        except (FileNotFoundError,PermissionError,ProcessLookupError,OSError):continue
        if target==path:raise ValueError('Card still open by a process')
    offset,length=window(path);before=path.stat()
    loop=None
    try:
        loop=subprocess.check_output(['losetup','--find','--show','--read-only','--offset',str(offset),
            '--sizelimit',str(length),str(path)],text=True).strip()
        if not re.fullmatch(r'/dev/loop\d+',loop):raise ValueError('Unexpected loop device')
        info=json.loads(subprocess.check_output(['losetup','--json','--output',
            'NAME,BACK-FILE,OFFSET,SIZELIMIT,RO',loop],text=True))['loopdevices']
        if len(info)!=1:raise ValueError('One owned loop view required')
        view=info[0]
        if (view['name']!=loop or Path(view['back-file']).resolve()!=path or not view['ro'] or
                int(view['offset'])!=offset or int(view['sizelimit'])!=length):
            raise ValueError('Loop view identity/read-only geometry mismatch')
        checked=subprocess.run(['fsck.exfat','-n',loop],text=True,capture_output=True)
        after=path.stat()
        return dict(source_card=str(path),derived_volume=str(path),partition_offset=offset,
            partition_bytes=length,fsck_exit=checked.returncode,fsck_output=checked.stdout+checked.stderr,
            source_unchanged=(before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),
            method='read-only-loop-view-no-volume-copy',loop_identity=view,
            capture_verified=False,codec_verified=False)
    finally:
        if loop is not None:
            subprocess.run(['losetup','--detach',loop],check=True)
