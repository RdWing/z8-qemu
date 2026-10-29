# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Actual-board default-off video decoder and immutable capability checks.

Loads only synthetic instructions/data. No camera firmware or media required.
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
bios=out/'synthetic.bin';bios.write_bytes(bytes.fromhex('00000014'))
checks=[]
def check(n,b):
 checks.append(dict(name=n,passed=bool(b)))
 if not b:raise AssertionError(n)
proc=qmp=stream=sock=None
try:
 with tempfile.TemporaryDirectory(prefix='lp-') as td:
  endpoint=Path(td)/'qmp';qt=Path(td)/'qt'
  args=[str(options.qemu.resolve()),'-M','nikon-z8-lab,bootstrap-fixtures=on,bus-window-fixture=on,wave5-vpu-model=on,wave5-host-codec-diagnostic=on','-cpu','cortex-a53','-smp','4','-m','512M','-kernel',str(bios),'-accel','qtest','-display','none','-serial','none','-monitor','none','-qmp',f'unix:{endpoint},server=on,wait=off','-qtest',f'unix:{qt},server=on,wait=off']
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
   w(0x100,op);w(0x70,1);w(0x6c if core else 0x38,1)
   check('command success',rd(base+0x108)==1)
  data(0xa00010000,b'\x5a'*4096)
  for off,v in [(0x110,0x40010000),(0x114,4096),(0x11c,0x40020000),(0x120,4096)]:w(off,v)
  command(1,True)
  w(0x110,0);w(0x104,0);command(0x4000)
  check('default profile advertises encoders only',rd(base+0x128)==3)
  check('decoder backend defaults off',qmp.command('qom-get',path='/machine',property='wave5-host-decoder-diagnostic') is False)
  rejected=False
  try:qmp.command('qom-set',path='/machine',property='wave5-host-decoder-diagnostic',value=True)
  except RuntimeError:rejected=True
  check('decoder backend cannot be enabled after realization',rejected and qmp.command('qom-get',path='/machine',property='wave5-host-decoder-diagnostic') is False)
  for off,value in [(0x110,0),(0x114,0x40030000),(0x118,0x10000),(0x11c,0x40040000),(0x120,0x100000),(0x124,15)]:w(off,value)
  w(0x100,8);w(0x70,1);w(0x38,1)
  state=json.loads(qmp.command('qom-get',path='/machine',property='wave5-vpu-state'))
  check('disabled decoder creates no instance or completion',state['commands']==2 and state['rejects']==1 and state['pending']==0 and not any(i['created'] for i in state['instances']))
  check('disabled decoder creates no input or output bytes',state['input_bytes']==0 and state['output_bytes']==0)

finally:
 if qmp: qmp.close()
 if stream:stream.close()
 if sock:sock.close()
 if proc:stop_child(proc,None)
 (out/'report.json').write_text(json.dumps(dict(original_firmware_loaded=False,qemu_sha256=hashlib.sha256(options.qemu.read_bytes()).hexdigest(),checks=checks),indent=2)+'\n')
print(len(checks),'checks passed')
