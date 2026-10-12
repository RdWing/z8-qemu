# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Create fresh image files and format only their verified virtual disks.

exFAT is generated with native macOS utilities or Linux exfatprogs, then
placed in an MBR partition. No camera files, firmware, or filesystem
implementation is copied.
Boot-region field/checksum reference:
https://learn.microsoft.com/en-us/windows/win32/fileio/exfat-specification
"""
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import plistlib
from contextlib import contextmanager




def extents(stream,length):
    position=0
    while position<length:
        try:start=os.lseek(stream.fileno(),position,os.SEEK_DATA)
        except OSError as exc:
            if exc.errno==errno.ENXIO:return
            raise
        end=min(length,os.lseek(stream.fileno(),start,os.SEEK_HOLE))
        yield start,end
        position=end


@contextmanager
def attached_image(path):
    """Attach only the supplied regular image, unmounted, and always detach it."""
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('Regular image file required')
    path = path.resolve()
    attached = plistlib.loads(subprocess.check_output([
        'hdiutil', 'attach', '-nomount', '-noverify', '-noautofsck',
        '-imagekey', 'diskimage-class=CRawDiskImage', '-plist', str(path)]))
    devices = [e['dev-entry'] for e in attached['system-entities']
               if re.fullmatch(r'/dev/disk[0-9]+', e.get('dev-entry', ''))]
    if len(devices) != 1:
        raise ValueError('One whole virtual disk required')
    device = devices[0]
    try:
        info = plistlib.loads(subprocess.check_output(['hdiutil', 'info', '-plist']))
        owners = [image for image in info['images']
                  if Path(image['image-path']).resolve() == path
                  and any(e.get('dev-entry') == device for e in image['system-entities'])]
        if len(owners) != 1:
            raise ValueError('Attached disk does not belong to the supplied image')
        yield device
    finally:
        subprocess.run(['hdiutil', 'detach', device], check=True, capture_output=True)


def format_volume(path, length):
    if sys.platform == 'darwin':
        with attached_image(path) as device:
            command = ['/sbin/newfs_exfat', '-S', '512', '-c', '256',
                       '-s', str(length // 512), '-v', 'Z8QEMU', device]
            result = subprocess.run(command, check=True, text=True, capture_output=True)
        return command, result
    command = ['mkfs.exfat', '-L', 'Z8QEMU', '-c', '128K', str(path)]
    return command, subprocess.run(command, check=True, text=True, capture_output=True)


def check_volume(path):
    if sys.platform == 'darwin':
        with attached_image(path) as device:
            return subprocess.run(['/sbin/fsck_exfat', '-n', device],
                                  text=True, capture_output=True)
    return subprocess.run(['fsck.exfat', '-n', str(path)], text=True, capture_output=True)


def create(path,filesystem='blank'):
    path=Path(path).resolve()
    if os.name=='nt':raise ValueError('Use macOS, Linux or a Linux WSL distribution')
    if path.suffix!='.raw' or not path.parent.is_dir():raise ValueError('fresh regular .raw file in an existing run directory required')
    if filesystem not in ('blank','exfat'):raise ValueError('unsupported card fixture')
    size=(128 if filesystem=='blank' else 8192)*1024*1024
    with path.open('xb') as stream:stream.truncate(size)
    result=dict(path=str(path),bytes=size,format='raw',filesystem=filesystem,
        initially_blank=filesystem=='blank',camera_files_supplied=False,
        physical_card_identity_verified=False,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    if filesystem=='exfat':
        partition=path.with_name(path.stem+'-initial-volume.raw')
        offset=1024*1024;length=size-offset
        with partition.open('xb') as stream:stream.truncate(length)
        command,formatted=format_volume(partition,length)
        with partition.open('r+b') as stream:
            for boot_start in (0,12*512):
                stream.seek(boot_start);region=bytearray(stream.read(11*512))
                if region[3:11]!=b'EXFAT   ' or region[108]!=9:raise ValueError('512-byte exFAT expected')
                struct.pack_into('<Q',region,64,offset//512)
                checksum=0
                for i,value in enumerate(region):
                    if i not in (106,107,112):
                        checksum=(((checksum>>1)|((checksum&1)<<31))+value)&0xffffffff
                stream.seek(boot_start);stream.write(region)
                stream.write(struct.pack('<I',checksum)*128)
        checked=check_volume(partition)
        checked.check_returncode()
        mbr=bytearray(512)
        struct.pack_into('<B3sB3sII',mbr,446,0,b'\x20\x21\x00',7,b'\xfe\xff\xff',offset//512,length//512)
        mbr[510:]=b'\x55\xaa'
        copied=[]
        with partition.open('rb') as source,path.open('r+b') as target:
            target.write(mbr)
            for start,end in extents(source,length):
                digest=hashlib.sha256();position=start
                while position<end:
                    source.seek(position);data=source.read(min(1024*1024,end-position))
                    target.seek(offset+position);target.write(data);digest.update(data);position+=len(data)
                copied.append(dict(start=start,end=end,sha256=digest.hexdigest()))
            target.flush()
            for part in copied:
                target.seek(offset+part['start']);digest=hashlib.sha256();left=part['end']-part['start']
                while left:
                    data=target.read(min(left,1024*1024));digest.update(data);left-=len(data)
                if digest.hexdigest()!=part['sha256']:raise ValueError('partition copy mismatch')
        result.update(partition_offset=offset,partition_bytes=length,format_command=command,
            format_output=formatted.stdout+formatted.stderr,fsck_output=checked.stdout+checked.stderr,
            initial_allocated_partition_extents=copied,mbr_sha256=hashlib.sha256(mbr).hexdigest(),
            sparse_zero_holes=True,initial_volume=str(partition),allocated_bytes=path.stat().st_blocks*512)
    path.with_suffix('.initial.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


def audit(path):
    """After QEMU exits, extract its partition into a fresh sparse file and fsck -n.

    This checks filesystem integrity, not capture or codec correctness.
    """
    path=Path(path).resolve()
    if os.name=='nt' or not path.is_file():
        raise ValueError('Existing regular card image required')
    before=path.stat();output=path.with_name(path.stem+'-after-volume.raw')
    with path.open('rb') as source:
        mbr=source.read(512)
        if mbr[510:]!=b'\x55\xaa' or mbr[450]!=7:raise ValueError('expected generated exFAT partition')
        start,sectors=struct.unpack_from('<II',mbr,454);offset=start*512;length=sectors*512
        if offset<512 or not length or offset+length>before.st_size:raise ValueError('invalid partition bounds')
        with output.open('xb') as target:
            target.truncate(length)
            for first,last in extents(source,before.st_size):
                first=max(first,offset);last=min(last,offset+length)
                while first<last:
                    source.seek(first);data=source.read(min(last-first,1024*1024))
                    target.seek(first-offset);target.write(data);first+=len(data)
    checked=check_volume(output)
    text=checked.stdout+checked.stderr;counts=re.search(r'directories (\d+), files (\d+)',text)
    after=path.stat()
    result=dict(source_card=str(path),derived_volume=str(output),fsck_exit=checked.returncode,
        fsck_output=text,source_unchanged=(before.st_size,before.st_mtime_ns)==(after.st_size,after.st_mtime_ns),
        directories=int(counts[1]) if counts else None,files=int(counts[2]) if counts else None,
        capture_verified=False,codec_verified=False,
        auditor_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    path.with_suffix('.audit.json').write_text(json.dumps(result,indent=2)+'\n')
    return result


if __name__=='__main__':
    import argparse
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--audit-card',type=Path,required=True)
    args=ap.parse_args();print(json.dumps(audit(args.audit_card)))
