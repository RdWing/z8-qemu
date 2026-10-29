# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Actual-board generated NV12 decode, resize, STOP and cancellation checks.

Uses an installed FFmpeg/libx265 encoder and NumPy to generate declared pixels.
No original firmware, saved camera media or external image inputs are loaded.
"""
import argparse,hashlib,sys,json,socket,tempfile,subprocess
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from qemu_control import QMP,stop_child,wait_for_sockets
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--qemu',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
options=parser.parse_args()
out=options.output.resolve();out.mkdir(parents=True,exist_ok=False)
import numpy as np
width,height=3840,2160
xx=np.arange(width,dtype=np.uint32)[None,:];yy=np.arange(height,dtype=np.uint32)[:,None]
cx=np.arange(width//2,dtype=np.uint32)[None,:];cy=np.arange(height//2,dtype=np.uint32)[:,None]
reference=((xx+2*yy)&255).astype(np.uint8).tobytes()+((3*cx+5*cy)&255).astype(np.uint8).tobytes()+((127+cx-cy)&255).astype(np.uint8).tobytes()
media=out/'synthetic.hevc'
subprocess.run(['ffmpeg','-v','error','-f','rawvideo','-pixel_format','yuv420p',
 '-video_size',f'{width}x{height}','-framerate','30','-i','pipe:0','-an',
 '-c:v','libx265','-x265-params','lossless=1:aud=1:bframes=0:rc-lookahead=0:log-level=error',
 '-f','hevc',str(media)],input=reference,check=True)
stream_bytes=media.read_bytes()

bios=out/'synthetic.bin';bios.write_bytes(bytes.fromhex('00000014'))
checks=[]
def check(n,b):
 checks.append(dict(name=n,passed=bool(b)))
 if not b:raise AssertionError(n)
proc=qmp=stream=sock=None
try:
 with tempfile.TemporaryDirectory(prefix='lp-') as td:
  endpoint=Path(td)/'qmp';qt=Path(td)/'qt'
  args=[str(options.qemu.resolve()),'-M','nikon-z8-lab,bootstrap-fixtures=on,bus-window-fixture=on,wave5-vpu-model=on,wave5-host-codec-diagnostic=on,wave5-host-decoder-diagnostic=on','-cpu','cortex-a53','-smp','4','-m','512M','-kernel',str(bios),'-accel','qtest','-display','none','-serial','none','-monitor','none','-qmp',f'unix:{endpoint},server=on,wait=off','-qtest',f'unix:{qt},server=on,wait=off']
  log=(out/'qemu.log').open('wb');proc=subprocess.Popen(args,stdout=log,stderr=log)
  wait_for_sockets(proc,endpoint,qt);qmp=QMP(endpoint);sock=socket.socket(socket.AF_UNIX);sock.connect(str(qt));stream=sock.makefile('rwb',buffering=0)
  irq_events=[]
  def cmd(x):
   stream.write((x+'\n').encode())
   while True:
    r=stream.readline().decode().strip()
    if r.startswith('IRQ '):irq_events.append(r);continue
    if not r.startswith('OK'):raise RuntimeError(r)
    return r.split()[1:]
  def wr(a,v):cmd(f'writel {a:#x} {v:#x}')
  def rd(a):return int(cmd(f'readl {a:#x}')[0],0)
  def data(a,b):cmd(f'write {a:#x} {len(b):#x} 0x{b.hex()}')
  def read(a,n):return bytes.fromhex(cmd(f'read {a:#x} {n:#x}')[0][2:])
  base=0x16010000
  def w(off,value):wr(base+off,value)
  def command(op,core=False):
   before=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))['commands']
   w(0x100,op);w(0x70,1);w(0x6c if core else 0x38,1)
   if op==0x100:
    early=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
    check('picture remains busy with no early completion IRQ',not early['busy'] and not (early['pending']&256))
    cmd('clock_step 999999')
    waiting=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
    check('picture cannot complete before declared functional deadline',not waiting['busy'] and waiting['output_bytes']==early['output_bytes'] and not (waiting['pending']&256))
    cmd('clock_step 1')
   after=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
   check('command accepted without stale status',after['commands']==before+1 and after['rejects']==0 and rd(base+0x108)==1)
  data(0xa00010000,b'\x5a'*4096)
  for off,v in [(0x110,0x40010000),(0x114,4096),(0x11c,0x40020000),(0x120,4096)]:w(off,v)
  command(1,True)
  w(0x110,0);w(0x104,0);command(0x4000)
  check('explicit functional decode capability',rd(base+0x128)==15)
  for off,v in [(0x110,0),(0x114,0x40030000),(0x118,0x10000),(0x11c,0x40040000),(0x120,0x405f800),(0x124,0)]:w(off,v)
  command(8);w(0x34,8)
  data(0xa00040000,stream_bytes)
  w(0x118,0x40040000);w(0x11c,0x40040000+len(stream_bytes));w(0x120,0);w(0x104,0)
  command(0x40);w(0x34,64);w(0x104,2);command(0x4000)
  check('actual parsed dimensions',rd(base+0x14c)==(3840<<16)|2160)
  check('actual parsed depth',rd(base+0x124)==0x88)
  state=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
  check('actual stream bytes consumed',0<state['input_bytes']<=len(stream_bytes))
  check('no rejected sequence work',state['rejects']==0)
  print('actual-board sequence',state['input_bytes'],state['instances'][0]['width'],state['instances'][0]['height'])
  width,height,stride=3840,2160,3840
  for off,value in [(0x104,0x18),(0x118,(1<<28)|(1<<23)|(1<<16)|stride),(0x11c,(width<<16)|height),(0x120,0),(0x134,0x48000000),(0x138,0x49000000),(0x13c,0)]:w(off,value)
  command(0x80)
  w(0x118,0x40040000);w(0x11c,0x40040000+len(stream_bytes));w(0x120,3);w(0x104,0)
  command(0x100);w(0x34,256);w(0x104,2);command(0x4000)
  state=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
  check('actual NV12 frame emitted',state['instances'][0]['pictures']==1 and state['output_bytes']==width*height*3//2)
  def chunked(phys,bytes):return b''.join(read(phys+o,min(262144,bytes-o)) for o in range(0,bytes,262144))
  import numpy as np
  ny=width*height;nc=ny//4
  yy=np.frombuffer(reference[:ny],dtype=np.uint8).reshape(height,width)
  uu=np.frombuffer(reference[ny:ny+nc],dtype=np.uint8).reshape(height//2,width//2)
  vv=np.frombuffer(reference[ny+nc:],dtype=np.uint8).reshape(height//2,width//2)
  expected_uv=np.stack([uu,vv],axis=2).reshape(height//2,width)
  check('actual NV12 luma RAM',chunked(0xa08000000,ny)==yy.tobytes())
  check('actual interleaved chroma RAM',chunked(0xa09000000,ny//2)==expected_uv.tobytes())
  a={4:0x1002,8:0x10000000,0xc:0x31000000,0x10:1,0x18:0x11110,0x20:0x08000000,0x24:10,0x28:0x09000000,0x2c:10,0x38:stride,0x3c:stride,0x40:0x22,0x48:0x10,0x4c:width,0x50:height}
  b={0xc:0x11000000,0x10:1,0x20:0x0b000000,0x24:10,0x28:0x0b100000,0x2c:10,0x38:1024,0x3c:1024,0x40:0x22,0x48:0x11}
  f={0:2,4:1,8:0x1c00,0xc:0x1c00,0x10:0x7800,0x14:0x7800,0x18:width,0x1c:height,0x20:1,0x2c:1024,0x30:576}
  for base_addr,config in [(0x15421100,a),(0x15422400,b),(0x15423400,f)]:
   for off,value in config.items():wr(base_addr+off,value)
  for phys,span_bytes in [(0xa0b000000,1024*576),(0xa0b100000,1024*288)]:
   data(phys-16,b'Z'*16);data(phys+span_bytes,b'Y'*16)
  wr(0x15421104,0x1001)
  resized=json.loads(qmp.command('qom-get',path='/machine',property='z8-playback-state'))
  check('owned decoded Movie resize admitted',resized['jobs']==1 and resized['bytes']==1024*576*3//2 and not resized['pending'])
  xx=((0x1c00+np.arange(1024)*0x7800)*2)>>14
  ys=((0x1c00+np.arange(576)*0x7800)*2)>>14
  yc=(((0x1c00+np.arange(288)*2*0x7800)*2)>>14)//2
  xc=xx[::2]//2
  ey=yy[ys[:,None],xx[None,:]]
  euv=np.stack([uu[yc[:,None],xc[None,:]],vv[yc[:,None],xc[None,:]]],axis=2).reshape(288,1024)
  check('actual resized luma matches independent coordinates',chunked(0xa0b000000,1024*576)==ey.tobytes())
  check('actual resized NV12 chroma matches independent coordinates',chunked(0xa0b100000,1024*288)==euv.tobytes())
  for phys,span_bytes in [(0xa0b000000,1024*576),(0xa0b100000,1024*288)]:
   check('resize destination canaries preserved',read(phys-16,16)==b'Z'*16 and read(phys+span_bytes,16)==b'Y'*16)
  blocks=json.loads(qmp.command('qom-get',path='/machine',property='engine1542-state'))['blocks']
  check('actual transfer raises input and writer causes',blocks[1]['pending']==0x11 and blocks[7]['pending']==0x1000)
  wr(0x1542111c,0x11);wr(0x1542241c,0x1000)
  check('frame acknowledgment does not manufacture STOP',json.loads(qmp.command('qom-get',path='/machine',property='engine1542-state'))['blocks'][1]['pending']==0)
  wr(0x15421104,0x1000)
  check('finite STOP follows completed transfer',json.loads(qmp.command('qom-get',path='/machine',property='engine1542-state'))['blocks'][1]['pending']==0x10000)
  wr(0x1542111c,0x10000)
  before_wait=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
  w(0x118,0x40040000);w(0x11c,0x40040000+len(stream_bytes));w(0x120,0);w(0x104,0);command(0x100)
  waiting=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
  check('occupied display buffer retains a queued picture without completion',not waiting['busy'] and not waiting['pending'] and waiting['output_bytes']==before_wait['output_bytes'] and rd(base+0x1e0)==1<<16)
  command(0x10)
  cmd('clock_step 10000000')
  flushed=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
  check('flush cancels queued picture without later DMA or IRQ',flushed['output_bytes']==before_wait['output_bytes'] and not flushed['pending'] and rd(base+0x1e0)==0)
  w(0x104,3);w(0x118,0);w(0x11c,1);command(0x4000)
  w(0x118,0x40040000);w(0x11c,0x40040000+len(stream_bytes));w(0x120,0);w(0x104,0);command(0x100)
  w(0x34,256);w(0x104,2);command(0x4000)
  replay=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
  check('flush reposition replays actual pixels with a new decode epoch',replay['instances'][0]['pictures']==2 and replay['output_crc']==before_wait['output_crc'])
  w(0x118,0x40040000);w(0x11c,0x40040000+len(stream_bytes));w(0x120,0);w(0x104,0);command(0x100)
  w(0x50,1)
  reset=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
  check('reset frees decoder and invalidates every display lease',not reset['booted'] and not any(i['created'] for i in reset['instances']))
  cmd('clock_step 10000000')
  after_reset=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
  check('reset cancels queued picture with no ghost pixels or IRQ',after_reset['output_bytes']==replay['output_bytes'] and not after_reset['pending'])
  wr(0x15421104,0x1001)
  resized=json.loads(qmp.command('qom-get',path='/machine',property='z8-playback-state'))
  check('reset display surface cannot be replayed',resized['requests']==1 and resized['jobs']==1 and not resized['pending'])
  print('actual NV12 decode and owned resize',resized['bytes'],'bytes')

finally:
 if qmp: qmp.close()
 if stream:stream.close()
 if sock:sock.close()
 if proc:stop_child(proc,None)
 (out/'report.json').write_text(json.dumps(dict(original_firmware_loaded=False,qemu_sha256=hashlib.sha256(options.qemu.read_bytes()).hexdigest(),checks=checks),indent=2)+'\n')
print(len(checks),'checks passed')
