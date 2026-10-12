# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Bounded, read-only catalog of an extracted exFAT virtual-card volume.

Reports names/sizes only. A file entry is not proof of a decoded photograph.
Layout reference: Microsoft exFAT specification, sections3 and7.
"""
import argparse
import json
import math
from pathlib import Path
import struct


def catalog(path, base=0):
    path=Path(path)
    if not path.is_file():raise ValueError('regular extracted volume file required')
    size=path.stat().st_size-base;rows=[];visited=set()
    with path.open('rb') as stream:
        def read(offset,length):
            if offset<0 or length<0 or offset+length>size or length>16*1024*1024:
                raise ValueError('out-of-range volume read')
            stream.seek(base+offset);data=stream.read(length)
            if len(data)!=length:raise ValueError('short volume read')
            return data
        boot=read(0,512)
        if boot[3:11]!=b'EXFAT   ' or not 9<=boot[108]<=12 or boot[109]>16:
            raise ValueError('unsupported exFAT geometry')
        sector=1<<boot[108];cluster=sector<<boot[109]
        fat,fat_length,heap,count,root=struct.unpack_from('<IIIII',boot,80)
        if heap*sector+count*cluster>size or count*4+8>fat_length*sector:
            raise ValueError('inconsistent volume geometry')
        def clusters(first,length=None,contiguous=False):
            current=first;seen=set();remaining=math.ceil(length/cluster) if length is not None else None
            while current<0xfffffff8 and remaining!=0:
                if not 2<=current<count+2 or current in seen or len(seen)>=128:
                    raise ValueError('invalid or excessive directory cluster chain')
                seen.add(current);yield current
                if remaining is not None:remaining-=1
                current=current+1 if contiguous else struct.unpack('<I',read(fat*sector+current*4,4))[0]
        def directory(first,prefix='',length=None,contiguous=False,depth=0):
            if first in visited or depth>6 or len(rows)>1024:raise ValueError('directory traversal bound reached')
            visited.add(first)
            chunks=[];total=0
            for c in clusters(first,length,contiguous):
                total+=cluster
                if total>16*1024*1024:raise ValueError('directory byte bound reached')
                chunks.append(read(heap*sector+(c-2)*cluster,cluster))
            data=b''.join(chunks)
            i=0
            while i+32<=len(data):
                kind=data[i]
                if kind==0:return
                if kind!=0x85:i+=32;continue
                secondary=data[i+1];end=i+32*(secondary+1)
                if not 2<=secondary<=18 or end>len(data):raise ValueError('invalid file entry set')
                group=data[i:end];checksum=0
                for n,value in enumerate(group):
                    if n not in (2,3):checksum=(((checksum>>1)|((checksum&1)<<15))+value)&0xffff
                if checksum!=struct.unpack_from('<H',group,2)[0] or group[32]!=0xc0:
                    raise ValueError('file entry checksum or stream invalid')
                names=[group[o+2:o+32] for o in range(64,len(group),32) if group[o]==0xc1]
                name=b''.join(names)[:group[35]*2].decode('utf-16le')
                if len(name)!=group[35] or '/' in name or name in ('.','..'):
                    raise ValueError('unexpected directory name')
                attributes=struct.unpack_from('<H',group,4)[0]
                valid=struct.unpack_from('<Q',group,40)[0]
                start=struct.unpack_from('<I',group,52)[0]
                length=struct.unpack_from('<Q',group,56)[0]
                no_fat_chain=bool(group[33]&2)
                row=dict(path=prefix+name,directory=bool(attributes&0x10),bytes=length,
                    valid_bytes=valid,first_cluster=start,contiguous=no_fat_chain)
                if len(rows)>=1024:raise ValueError('directory entry bound reached')
                rows.append(row)
                if row['directory']:directory(start,prefix+name+'/',length,no_fat_chain,depth+1)
                i=end
        directory(root)
    return dict(volume=str(path),files=rows,capture_verified=False)


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('volume',type=Path)
    args=ap.parse_args();print(json.dumps(catalog(args.volume),indent=2))
