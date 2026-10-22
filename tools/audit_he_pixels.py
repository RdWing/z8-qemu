# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Compare a decoded functional HE Bayer plane with its explicit sensor input.

Requires NumPy. This measures the supplied synthetic frame, not camera quality.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import numpy as np
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--run',type=Path,required=True)
p.add_argument('--audit',type=Path,required=True)
p.add_argument('--raw',type=Path,required=True)
p.add_argument('--capture-index',type=int,default=1,help='One-based native capture snapshot, within 1..16')
a=p.parse_args()
if not 1<=a.capture_index<=16:p.error('Capture index must be within 1..16')
run=json.loads((a.run/'result.json').read_text());report=json.loads((a.audit/'report.json').read_text())
assert run['owned_qemu_stopped'] and not run['error'] and all(x['passed'] for x in run['checks'])
assert report['full_raw_decode']
assert hashlib.sha256(a.raw.read_bytes()).hexdigest()==run['raw_sha256']
with a.raw.open('rb') as f:magic,sw,sh,bits,cfa,black,white=struct.unpack('<8s6I',f.read(32))
assert magic==b'NZ9RAW1\0' and 0<sw<=16384 and 0<sh<=16384 and not((sw|sh)&1)
assert bits in (12,14,16) and cfa==black==0 and 0<white<=65535
assert a.raw.stat().st_size==32+sw*sh*2
w,h=report['width'],report['height'];assert not((w|h)&1)
raw=np.memmap(a.raw,dtype='<u2',mode='r',offset=32,shape=(sh,sw))
dec=np.memmap(a.audit/'bayer.u16',dtype='<u2',mode='r',shape=(h,w))
x=np.arange(w,dtype=np.int64);sx=(x//2*(sw//2)//(w//2))*2+(x&1)
maximum=0;total=0;source_mismatches=0;producer_max=0;producer_total=0;producer=None
snapshots=next((row for row in run.get('he_capture_snapshots',[]) if row['capture_index']==a.capture_index),None)
if snapshots is None and a.capture_index==1:snapshots=run.get('he_snapshots')
assert a.capture_index==1 or snapshots is not None,'Requested capture snapshot missing'
if snapshots:
 assert (snapshots['width'],snapshots['height'])==(w,h)
 pitch=snapshots['pitch'];assert (a.run/snapshots['input']).stat().st_size==pitch*h
 producer=np.memmap(a.run/snapshots['input'],dtype=np.uint8,mode='r',shape=(h,pitch))
 assert hashlib.sha256((a.run/snapshots['output']).read_bytes()).hexdigest()==report['raw_sha256']
for y in range(h):
 sy=(y//2*(sh//2)//(h//2))*2+(y&1)
 expected=np.minimum(16383,(raw[sy,sx].astype(np.uint64)*16383+white//2)//white).astype(np.int32)
 decoded=dec[y].astype(np.int32) # The public Bayer reconstruction retires the inverse transfer's scale.
 delta=np.abs(decoded-expected);maximum=max(maximum,int(delta.max()));total+=int(delta.sum())
 if producer is not None:
  # Decode arbitrary packed14 pitch without assuming width is divisible by four.
  at=x*14//8;shift=x*14%8;row=producer[y].astype(np.uint32)
  word=row[at]|row[at+1]<<8
  need=shift>2;word[need]|=row[at[need]+2]<<16
  pixels=((word>>shift)&16383).astype(np.int32)
  source_mismatches+=int(np.count_nonzero(pixels!=expected))
  d=np.abs(decoded-pixels);producer_max=max(producer_max,int(d.max()));producer_total+=int(d.sum())
result=dict(capture_index=a.capture_index,samples=w*h,width=w,height=h,decoded_scale=1,maximum_error_14bit=maximum,
 mean_absolute_error_14bit=total/(w*h),producer_compared=producer is not None,
 producer_input_mismatches=source_mismatches if producer is not None else None,
 receiver_strip_equal=True if snapshots else None,
 producer_maximum_error_14bit=producer_max if producer is not None else None,
 producer_mean_absolute_error_14bit=producer_total/(w*h) if producer is not None else None,
 scope='One supplied synthetic frame; functional HE arithmetic, no physical camera or photographic quality qualification')
assert producer is None or source_mismatches==0
(a.audit/'pixel-comparison.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
