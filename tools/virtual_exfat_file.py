# SPDX-License-Identifier: GPL-2.0-or-later
"""Read an initialized file from a private exFAT image without extracting it."""
import bisect, math, struct, threading
from pathlib import Path
from inspect_virtual_exfat import catalog
from virtual_exfat_window import window


class VirtualExfatFile:
    def __init__(self,volume,name):
        self.volume=Path(volume)
        self.origin,self.volume_bytes=window(self.volume)
        entries=[r for r in catalog(self.volume)['files'] if r['path']==name and not r['directory']]
        if len(entries)!=1:raise ValueError('One validated regular file required')
        self.entry=entries[0];self.size=self.entry['bytes']
        if not 0<self.size<=self.volume_bytes or self.entry['valid_bytes']!=self.size:
            raise ValueError('Complete initialized file required')
        self.lock=threading.Lock();self.stream=self.volume.open('rb')
        self.stream.seek(self.origin);boot=self.stream.read(512)
        sector=1<<boot[108];self.cluster=sector<<boot[109]
        fat,_,heap,count,_=struct.unpack_from('<IIIII',boot,80)
        self.extents=[];seen=set();current=self.entry['first_cluster'];logical=0
        try:
            table=None
            if not self.entry['contiguous']:
                length=count*4+8
                if length>32*1024*1024:raise ValueError('FAT metadata bound exceeded')
                self.stream.seek(self.origin+fat*sector);table=self.stream.read(length)
                if len(table)!=length:raise ValueError('Short FAT table')
            for _ in range(math.ceil(self.size/self.cluster)):
                if not 2<=current<count+2 or current in seen:raise ValueError('Invalid or cyclic file chain')
                seen.add(current);physical=self.origin+heap*sector+(current-2)*self.cluster
                length=min(self.cluster,self.size-logical)
                if physical+length>self.origin+self.volume_bytes:raise ValueError('File span outside volume')
                if self.extents and self.extents[-1][1]+self.extents[-1][2]==physical:
                    start,offset,n=self.extents[-1];self.extents[-1]=(start,offset,n+length)
                else:self.extents.append((logical,physical,length))
                logical+=length
                if logical<self.size:
                    if self.entry['contiguous']:current+=1
                    else:current=struct.unpack_from('<I',table,current*4)[0]
            self.starts=[v[0] for v in self.extents]
        except BaseException:
            self.stream.close();raise

    def read_at(self,offset,length):
        if not isinstance(offset,int) or not isinstance(length,int) or offset<0 or length<0 or offset+length>self.size:
            raise ValueError('Read outside initialized file')
        if length>32*1024*1024:raise ValueError('Bounded reads required')
        pieces=[]
        with self.lock:
            while length:
                i=bisect.bisect_right(self.starts,offset)-1
                logical,physical,n=self.extents[i];take=min(length,logical+n-offset)
                if take<=0:raise ValueError('Missing file extent')
                self.stream.seek(physical+offset-logical);data=self.stream.read(take)
                if len(data)!=take:raise ValueError('Short image read')
                pieces.append(data);offset+=take;length-=take
        return b''.join(pieces)

    def close(self):self.stream.close()
