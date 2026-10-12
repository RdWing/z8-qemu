# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Independent full Z8 file decode and synthetic input oracle; no writes to camera files."""
from pathlib import Path
import sys,json,hashlib,struct,io,subprocess
import numpy as np
import rawpy
from PIL import Image
P=Path(__file__).resolve().parent
from nef_ifds import image_ifds, require_lossless14
import argparse
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--firmware',type=Path,required=True);p.add_argument('--raw',type=Path,required=True)
p.add_argument('--adobe-dng',type=Path,help='Optional Adobe-converted DNG for a second decoder sample comparison')
a=p.parse_args();run=a.output.resolve();d=json.loads((run/'result.json').read_text())
assert d['owned_qemu_stopped'] and not d['ram_patches'] and not d['cpu_register_redirection']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
firmware=a.firmware
assert sha(firmware)==d['firmware_sha256']=='2b43a31c9de838f84b12416de4348a7004e65be07f853ec56ec2b10f3a8e3853'
nef=run/'DSC_0001.NEF';receipt=json.loads(nef.with_suffix('.NEF.extraction.json').read_text());data=nef.read_bytes()
assert sha(nef)==receipt['sha256'] and len(data)==receipt['bytes']==receipt['entry']['valid_bytes']
ifds=image_ifds(data);previews=[]
for row in ifds:
 t=row['tags']
 if 513 in t and 514 in t:
  off,n=t[513][0],t[514][0];assert n>0 and off+n<=len(data)
  blob=data[off:off+n]
  with Image.open(io.BytesIO(blob)) as im:im.load();size=list(im.size)
  name=f'preview-{size[0]}x{size[1]}.jpg';(run/name).write_bytes(blob)
  previews.append(dict(offset=off,bytes=n,size=size,sha256=hashlib.sha256(blob).hexdigest(),file=name))
assert all(list(s) in [r['size'] for r in previews] for s in [(8256,5504),(1620,1080),(160,120)])
rows=[r for r in ifds if r['tags'].get(254)==[0] and r['tags'].get(262)==[32803]];assert len(rows)==1
t=rows[0]['tags'];assert [t[k][0] for k in (256,257,258)]==[8280,5520,14]
assert len(t[273])==len(t[279]) and all(n>0 and off+n<=len(data) for off,n in zip(t[273],t[279]))
# Exclude LibRaw's size-based packed-pixel fallback before interpreting a
# successful decode as evidence of a valid Nikon lossless bitstream.
linearization=subprocess.check_output(['exiftool','-b','-NEFLinearizationTable',str(nef)])
require_lossless14(t,linearization)
fixture=a.raw;head=fixture.open('rb').read(32);assert head[:8]==b'NZ9RAW1\0'
sw,sh,bits,cfa,black,white=struct.unpack_from('<6I',head,8);assert (sw,sh,bits,cfa,black,white)==(8256,5504,14,0,0,16383)
assert sha(fixture)==d['raw_sha256']
source=np.memmap(fixture,dtype='<u2',mode='r',offset=32,shape=(sh,sw))
x=np.arange(8280,dtype=np.int64);sx=(x//2*(sw//2)//(8280//2))*2+(x&1)
producer=run/'engine151-raw-side-target.bin'
if not producer.is_file():raise ValueError('Capture RAW producer snapshot required for sample comparison')
assert producer.stat().st_size==14496*5520
actual=np.memmap(producer,dtype=np.uint8,mode='r',shape=(5520,14496))
mismatch=0;producer_mismatch=0
with rawpy.imread(str(nef)) as raw:
 decoded=raw.raw_image;assert decoded.shape==(5520,8280)
 decoded_sha=hashlib.sha256(decoded.tobytes()).hexdigest()
 for y in range(5520):
  sy=(y//2*(sh//2)//(5520//2))*2+(y&1)
  expected=source[sy,sx] # white=16383 makes the integer scale identity
  mismatch+=int(np.count_nonzero(decoded[y]!=expected))
  if actual is not None:
   groups=actual[y,:8280*14//8].reshape(-1,7).astype(np.uint64)
   words=sum(groups[:,b]<<(8*b) for b in range(7))
   pixels=np.stack([(words>>(14*b))&16383 for b in range(4)],axis=1).reshape(-1)
   producer_mismatch+=int(np.count_nonzero(decoded[y]!=pixels))
assert mismatch==0 and producer_mismatch==0
# Adobe conversion provides an independent decoder path. Compare the RAW
# samples, not the DNG preview or a colour-managed rendered image.
adobe=None
if a.adobe_dng:
 with rawpy.imread(str(nef)) as native, rawpy.imread(str(a.adobe_dng)) as converted:
  assert converted.raw_image.shape==native.raw_image.shape==(5520,8280)
  different=sum(int(np.count_nonzero(native.raw_image[y]!=converted.raw_image[y])) for y in range(5520))
  assert different==0, f'Adobe RAW sample mismatches: {different}'
  adobe={'dng_sha256':sha(a.adobe_dng),'decoded_samples':45705600,'raw_sample_mismatches':different}
meta=json.loads(subprocess.check_output(['exiftool','-j','-G1','-s',str(nef)],text=True))[0]
assert meta['Nikon:NEFCompression']=='Lossless'
assert meta['IFD0:Model']=='NIKON Z 8' and not any(k.endswith((':Warning',':Error')) for k in meta)
result={'session':run.name,'file_bytes':len(data),'file_sha256':sha(nef),'firmware_sha256':sha(firmware),'sensor_input_sha256':sha(fixture),'tool_sha256':sha(Path(__file__)),'full_file_accepted':adobe is not None,'nikon_lossless14_decoded':True,'libraw_packed_size_fallback_excluded':True,'rawpy':rawpy.__version__,'libraw':list(rawpy.libraw_version),'decoded_shape':[5520,8280],'decoded_samples':5520*8280,'decoded_sha256':decoded_sha,'synthetic_input_mismatches':mismatch,'producer_snapshot_compared':True,'producer_mismatches':producer_mismatch,'adobe_decode':adobe,'previews':previews,'picture_control':meta.get('Nikon:PictureControlName'),'camera_raw_defaults':{k:v for k,v in meta.items() if k.startswith('XMP-crd:')},'scope':'Firmware-written NEF with F0 lossless entropy coding. Synthetic pixels compared to the input and guest producer. Adobe cross-decoder acceptance is recorded only when an Adobe-converted DNG is supplied. Physical codec, ISP and image quality remain unmodeled.'}
(run/'native-nef-audit.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
