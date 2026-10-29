# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Actual-board decoder queue, pixels, leases and lifecycle regression.

Generates a lossless HEVC stream from declared pixels using installed FFmpeg.
No camera firmware, saved camera files or external media are loaded.
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
width,height,stride=128,128,160
source_frames=[bytes([40+n])* (width*height)+bytes([96+n])*(width*height//4)+bytes([160-n])*(width*height//4) for n in range(30)]
media=out/'synthetic.hevc'
subprocess.run(['ffmpeg','-v','error','-f','rawvideo','-pixel_format','yuv420p',
 '-video_size',f'{width}x{height}','-framerate','30','-i','pipe:0','-an',
 '-c:v','libx265','-x265-params','lossless=1:aud=1:keyint=15:bframes=0:rc-lookahead=0:log-level=error',
 '-f','hevc',str(media)],input=b''.join(source_frames),check=True)
all_stream=media.read_bytes()
starts=[n for n in range(len(all_stream)-5) if all_stream[n:n+5]==b'\0\0\0\1\x46']
assert len(starts)==30 and starts[0]==0
stream_bytes=all_stream[:starts[1]]

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
    check('picture queue acknowledged with no early completion IRQ',not early['busy'] and not (early['pending']&256))
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
  w(0x13c,3);command(8);w(0x34,8)
  data(0xa00040000,stream_bytes)
  w(0x118,0x40040000);w(0x11c,0x40040000+len(stream_bytes));w(0x120,0);w(0x104,0)
  command(0x40);w(0x34,64);w(0x104,2);command(0x4000)
  check('actual parsed dimensions',rd(base+0x14c)==(width<<16)|height)
  check('actual parsed depth',rd(base+0x124)==0x88)
  state=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
  check('actual stream bytes consumed',0<state['input_bytes']<=len(stream_bytes))
  check('no rejected sequence work',state['rejects']==0)
  print('actual-board sequence',state['input_bytes'],state['instances'][0]['width'],state['instances'][0]['height'])
  check('actual HEVC profile',rd(base+0x120)>>24==1)
  def empty_result(label):
   before=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
   w(0x104,2);w(0x100,0x4000);w(0x70,1);w(0x38,1)
   after=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
   check(label,rd(base+0x108)==0 and rd(base+0x10c)==0x800 and after['commands']==before['commands']+1 and after['rejects']==0 and after['pending']==before['pending'] and after['output_bytes']==before['output_bytes'] and after['instances'][0]['pictures']==before['instances'][0]['pictures'])
  empty_result('sequence result cannot be consumed twice')
  all_planes=[]
  for slot in range(4):
   phys=0xa08000000+slot*0x1000000
   planes=[(phys,stride,height,width),(phys+0x900000,stride//2,height//2,width//2),(phys+0xc00000,stride//2,height//2,width//2)]
   all_planes.append(planes)
   for address,pitch,rows,active in planes:
    data(address-16,b'Z'*16);data(address+pitch*rows,b'Y'*16)
  # Three opaque compressed reservations, independently from four linear slots.
  w(0x118,(1<<16)|stride);w(0x120,2)
  for slot in range(3):
   w(0x134+slot*16,0x46000000+slot*0x10000);w(0x138+slot*16,0x46008000+slot*0x10000)
  command(0x80)
  w(0x118,(1<<28)|(1<<23)|stride);w(0x120,3)
  for slot,planes in enumerate(all_planes):
   for plane,(phys,pitch,rows,active) in enumerate(planes):w(0x134+slot*16+plane*4,0x40000000+phys-0xa00000000)
  command(0x80)
  data(0xa00040000,all_stream)
  w(0x11c,0x40040000+len(stream_bytes));w(0x120,0);command(0x8000)
  import zlib
  reference=[zlib.crc32(f) for f in source_frames]
  def chunked(phys,bytes):return b''.join(read(phys+o,min(262144,bytes-o)) for o in range(0,bytes,262144))
  au_starts=[n for n in range(len(all_stream)-5) if all_stream[n:n+5]==b'\0\0\0\1\x46']
  assert len(au_starts)==30
  au_ends=au_starts[1:]+[len(all_stream)]
  total=0;queued_starts={}
  for frame in range(30):
   if frame>=4:
    w(0x104,3);w(0x118,0);w(0x11c,1<<(frame%3));command(0x4000)
   w(0x118,0x40040000);w(0x11c,0x40040000+au_ends[frame]);w(0x120,3 if frame==29 else 0);w(0x104,0)
   start_ns=int(cmd('clock_step 1')[0],0)
   for off,value in [(0x168,0xdeadbeef),(0x19c,0xf00d1234),(0x1b8,0xfedcba98),(0x1d0,0x1234567)]:w(off,value)
   if frame in (4,5,6):
    start_ns=queued_starts[frame]
    cmd('clock_step 1000000')
   else:command(0x100)
   if frame==3:
    blocked=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
    check('fourth picture waits despite a free fourth linear buffer',blocked['instances'][0]['pictures']==3 and blocked['output_bytes']==3*width*height*3//2 and not blocked['pending'] and not blocked['busy'] and rd(base+0x1e0)==1<<16)
    empty_result('queued picture without a reference has no result')
    cmd('clock_step 5000000')
    unchanged=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
    check('waiting alone cannot create pixels or IRQ',unchanged['output_bytes']==blocked['output_bytes'] and unchanged['instances'][0]['pictures']==3 and not unchanged['pending'])
    for queued_frame in (4,5,6):
     queued_starts[queued_frame]=int(cmd('clock_step 1')[0],0)
     w(0x118,0x40040000);w(0x11c,0x40040000+au_ends[queued_frame]);w(0x120,0);command(0x100)
    check('four held commands admitted at programmed native depth',rd(base+0x1e0)==4<<16)
    w(0x118,0xdead0000);w(0x11c,0xbeef0000);w(0x120,3)
    w(0x100,0x100);w(0x70,1);w(0x38,1)
    check('fifth held command returns true queue full without replacing submitted arguments',rd(base+0x108)==0 and rd(base+0x10c)==1 and rd(base+0x1e0)==4<<16)
    w(0x104,3);w(0x118,0);w(0x11c,1);command(0x4000)
    check('display release schedules rather than completes pending picture',json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))['output_bytes']==blocked['output_bytes'])
    cmd('clock_step 1000000')
   w(0x34,256);w(0x104,2);command(0x4000)
   end_ns=int(cmd('clock_step 1')[0],0)
   check(f'frame {frame} absent auxiliary metadata cannot leak command addresses',rd(base+0x168)==0 and rd(base+0x19c)==0)
   check(f'frame {frame} command timestamp comes from actual virtual submission',rd(base+0x1b8)==(start_ns//256)&0xffffffff)
   check(f'frame {frame} completion timestamp comes from actual virtual DMA completion',rd(base+0x1d0)==((end_ns-1)//256)&0xffffffff)
   check(f'frame {frame} actual decoded CRC',json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))['output_crc']==reference[frame])
   slot=frame%3;planes=all_planes[slot]
   check(f'frame {frame} distinct linear display index',rd(base+0x174)==slot)
   check(f'frame {frame} actual native linear decode index',rd(base+0x170)==slot)
   if frame in (0,29):
    actual=bytearray()
    for phys,pitch,rows,active in planes:
     body=chunked(phys,pitch*rows)
     actual+=b''.join(body[y*pitch:y*pitch+active] for y in range(rows))
     check(f'frame {frame} row padding unchanged',all(body[y*pitch+active:(y+1)*pitch]==bytes(pitch-active) for y in range(rows)))
     check(f'frame {frame} destination canaries',read(phys-16,16)==b'Z'*16 and read(phys+pitch*rows,16)==b'Y'*16)
    check(f'frame {frame} actual output RAM CRC',zlib.crc32(actual)==reference[frame])
   empty_result(f'frame {frame} drained result reports not ready')
  w(0x104,3);w(0x118,0);w(0x11c,15);command(0x4000)
  w(0x118,0x40040000);w(0x11c,0x40040000+len(all_stream));w(0x120,3);w(0x104,0)
  command(0x100);w(0x34,256);w(0x104,2);command(0x4000)
  check('real parser and decoder drain gives sequence end',rd(base+0x174)==0xffffffff and rd(base+0x170)==0xfffffffe)
  state=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
  check('exactly thirty actual output surfaces',state['instances'][0]['pictures']==30 and state['output_bytes']==30*width*height*3//2)
  command(0x10)
  w(0x118,0x40040000);w(0x11c,0x40040000+len(stream_bytes));w(0x120,0);w(0x104,0)
  command(0x100);w(0x34,256);w(0x104,2);command(0x4000)
  replay=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
  check('explicit flush and read reposition decode the real first frame again',replay['instances'][0]['pictures']==31 and replay['output_crc']==reference[0])
  empty_result('flushed replay result cannot be consumed twice')
  # Fill all three reference leases with real pictures, then cancel an
  # entire programmed four-command queue without fabricated completions.
  for reset in (False,True):
   if reset:
    w(0x104,3);w(0x118,0);w(0x11c,7);command(0x4000)
    first=0
   else:first=1
   for frame in range(first,3):
    w(0x118,0x40040000);w(0x11c,0x40040000+au_ends[frame]);w(0x120,0);command(0x100)
    w(0x34,256);w(0x104,2);command(0x4000)
   held=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
   for frame in range(3,7):
    w(0x118,0x40040000);w(0x11c,0x40040000+au_ends[frame]);w(0x120,0);command(0x100)
   check('all four pending commands retain no premature result',rd(base+0x1e0)==4<<16)
   if reset:w(0x50,1)
   else:command(0x10)
   cmd('clock_step 10000000')
   cancelled=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
   check('reset or flush cancels all queued DMA and IRQ',cancelled['output_bytes']==held['output_bytes'] and not cancelled['pending'] and not cancelled['busy'])
   if reset:check('reset closes every decoder instance',not any(i['created'] for i in cancelled['instances']))
  print('actual-board decoded pictures',30,'real bytes',state['output_bytes'])

finally:
 if qmp: qmp.close()
 if stream:stream.close()
 if sock:sock.close()
 if proc:stop_child(proc,None)
 (out/'report.json').write_text(json.dumps(dict(original_firmware_loaded=False,qemu_sha256=hashlib.sha256(options.qemu.read_bytes()).hexdigest(),checks=checks),indent=2)+'\n')
print(len(checks),'checks passed')
