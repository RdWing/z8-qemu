# SPDX-License-Identifier: GPL-2.0-or-later
"""Index single-track RAW movies from bounded ISO BMFF metadata only.

Do not read 28 GB of frame payload merely to obtain a packet offset list.
Actual payload bytes and independent codec decoding remain separate checks.
"""
import struct


def boxes(data):
    at=0
    while at<len(data):
        if at+8>len(data):raise ValueError('Short metadata box')
        size,kind=struct.unpack_from('>I4s',data,at);head=8
        if size==1:
            if at+16>len(data):raise ValueError('Short extended box')
            size=struct.unpack_from('>Q',data,at+8)[0];head=16
        if size==0:size=len(data)-at
        if size<head or size>len(data)-at:raise ValueError('Metadata box bound')
        yield kind,data[at+head:at+size]
        at+=size


def one(data,kind):
    rows=[body for tag,body in boxes(data) if tag==kind]
    if len(rows)!=1:raise ValueError('One '+repr(kind)+' required')
    return rows[0]


def table(data,columns,width=4):
    if len(data)<8 or data[:4]!=b'\0'*4:raise ValueError('Version0 metadata table required')
    count=struct.unpack_from('>I',data,4)[0]
    if count>1000000 or len(data)!=8+count*columns*width:raise ValueError('Metadata table bound')
    return list(struct.iter_unpack('>'+('I' if width==4 else 'Q')*columns,data[8:]))


def raw_packets(reader,stream_index=0):
    at=0;moov=None
    while at<reader.size:
        if reader.size-at<8:raise ValueError('Short top-level box')
        head=reader.read_at(at,min(16,reader.size-at));size,kind=struct.unpack_from('>I4s',head);offset=8
        if size==1:
            if len(head)<16:raise ValueError('Short large box')
            size=struct.unpack_from('>Q',head,8)[0];offset=16
        if not size:size=reader.size-at
        if size<offset or size>reader.size-at:raise ValueError('Top-level movie box bound')
        if kind==b'moov':
            if moov is not None or size>16*1024*1024:raise ValueError('One bounded moov required')
            moov=reader.read_at(at+offset,size-offset)
        at+=size
    if moov is None:raise ValueError('Movie metadata missing')
    tracks=[body for kind,body in boxes(moov) if kind==b'trak']
    if len(tracks)!=1:raise ValueError('Single-track RAW movie required')
    mdia=one(tracks[0],b'mdia');handler=one(mdia,b'hdlr')
    if len(handler)<12 or handler[8:12]!=b'vide':raise ValueError('Video handler required')
    stbl=one(one(mdia,b'minf'),b'stbl');sizes=one(stbl,b'stsz')
    if len(sizes)<12 or sizes[:4]!=b'\0'*4:raise ValueError('Version0 stsz required')
    constant,count=struct.unpack_from('>II',sizes,4)
    if not 0<count<=1000000:raise ValueError('Sample count bound')
    if constant:
        if len(sizes)!=12:raise ValueError('Constant-size sample table bound')
        lengths=[constant]*count
    else:
        if len(sizes)!=12+4*count:raise ValueError('Variable sample table bound')
        lengths=list(struct.unpack('>'+'I'*count,sizes[12:]))
    children=dict(boxes(stbl))
    if (b'stco' in children)==(b'co64' in children):raise ValueError('One chunk-offset table required')
    chunks=[v[0] for v in table(children.get(b'stco',children.get(b'co64')),1,4 if b'stco' in children else 8)]
    mapping=table(one(stbl,b'stsc'),3)
    if not mapping or mapping[0][0]!=1 or any(row[1]==0 or row[2]!=1 for row in mapping):raise ValueError('Qualified sample/chunk mapping required')
    if any(a[0]>=b[0] for a,b in zip(mapping,mapping[1:])):raise ValueError('Monotonic chunk mapping required')
    positions=[];rule=0;sample=0
    for chunk,offset in enumerate(chunks,1):
        while rule+1<len(mapping) and mapping[rule+1][0]<=chunk:rule+=1
        for _ in range(mapping[rule][1]):
            if sample>=count or not lengths[sample] or offset>reader.size-lengths[sample]:raise ValueError('Sample range bound')
            positions.append(offset);offset+=lengths[sample];sample+=1
    if sample!=count:raise ValueError('Incomplete sample mapping')
    durations=[]
    for repeat,delta in table(one(stbl,b'stts'),2):
        if repeat>count-len(durations) or not delta:raise ValueError('Sample timing bound')
        durations.extend([delta]*repeat)
    if len(durations)!=count:raise ValueError('Incomplete sample timing')
    if b'ctts' in children and any(offset for _,offset in table(children[b'ctts'],2)):
        raise ValueError('Reordered RAW samples outside qualified scope')
    pts=0;packets=[]
    for offset,size,delta in zip(positions,lengths,durations):
        packets.append(dict(stream_index=stream_index,pts=pts,size=str(size),pos=str(offset)))
        pts+=delta
    return packets
