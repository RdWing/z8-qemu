# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Actual-board LPCM RAM, mailbox ownership, IRQ and rejection checks.

Loads only synthetic instructions/data. No camera firmware or media required.
"""
import argparse,hashlib,sys,json,socket,tempfile,subprocess
from pathlib import Path

from qemu_control import QMP,stop_child,wait_for_sockets
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--qemu',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
parser.add_argument('--disabled',action='store_true',help='Verify the default-off boot gate only')
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
  args=[str(options.qemu.resolve()),'-M','nikon-z8-lab,bootstrap-fixtures=on,bus-window-fixture=on'+('' if options.disabled else ',lpcm-host-conversion-model=on,lpcm-ram-aperture-fixture=on'),'-cpu','cortex-a53','-smp','4','-m','512M','-kernel',str(bios),'-accel','qtest','-display','none','-serial','none','-monitor','none','-qmp',f'unix:{endpoint},server=on,wait=off','-qtest',f'unix:{qt},server=on,wait=off']
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
  gics=[c for c in qmp.command('qom-list',path='/machine/unattached') if c['type']=='child<arm-gicv3>'];assert len(gics)==1
  cmd('irq_intercept_in /machine/unattached/'+gics[0]['name'])
  wr(0x1b80002c,0x10);cmd('clock_step 1000000');check('empty upload cannot boot',rd(0xa00080000)==0)
  if options.disabled:
   data(0xa00000000,b'\x5a'*2048);wr(0x1b80002c,0x10);cmd('clock_step 1000000')
   check('default profile does not provide a boot result',rd(0xa00080000)==0)
   check('default model disabled',not json.loads(qmp.command('qom-get',path='/machine',property='lpcm-host-state'))['enabled'])
   raise SystemExit(0)
  data(0xa00000000,b'\x5a'*2048);wr(0x1b80002c,0x10);cmd('clock_step 1000000');check('boot protocol',rd(0xa00080000)==0x53535353)
  def request(words):
   irq_events.clear()
   wr(0x1b802100,1);wr(0x1b802104,3);wr(0x1b802110,0x10)
   for i,v in enumerate(words+[0]*(9-len(words))):wr(0x1b802140+i*4,v)
   wr(0x1b802108,1)
   check('RX waits for TX ownership',rd(0x1b802084)==0)
   cmd('clock_step 1000000');check('TX descriptor',rd(0x1b802080)==0x100);check('TX IRQ86 wire','IRQ raise 54' in irq_events)
   wr(0x1b802134,0x10);check('RX waits for claim release',rd(0x1b802084)==0)
   wr(0x1b802100,0);check('RX descriptor',rd(0x1b802084)==0x100);check('RX IRQ87 wire','IRQ raise 55' in irq_events)
   reply=[rd(0x1b802140+i*4) for i in range(9)];wr(0x1b802114,2)
   check('response identity',reply[:2]==words[:2]);check('RX acknowledged',rd(0x1b802084)==0)
  request([2,1,1,0x50010000,0x58040000])
  data(0xa10010000,bytes.fromhex('78563412876543fe'))
  request([2,3,8,6])
  check('first aperture beyond 128MiB read/write mapping',read(0xa10040000,6)==bytes.fromhex('5634126543fe'))
  request([2,2])
  for base,local,physical in [(0x14160500,0x40000000,0x200000000),(0x14160540,0x50000000,0x200040000)]:
   for off,v in [(0,local),(8,0xffffc0000),(16,physical)]:cmd(f'writeq {base+off:#x} {v:#x}')
  source=bytes.fromhex('78563412876543fe000000800000007f')
  for mode,ib,ob in [(1,4,3),(2,3,4),(3,4,2),(4,3,2)]:
   request([2,1,mode,0x40001000,0x50001000]);b=source[:12] if ib==3 else source
   data(0xa00001000,b);request([2,3,len(b),len(b)//ib*ob])
   expected=b''.join((b[i+ib-ob:i+ib] if ob<ib else b'\x00'*(ob-ib)+b[i:i+ib]) for i in range(0,len(b),ib))
   check(f'mode {mode} actual RAM conversion',read(0xa00041000,len(expected))==expected)
   request([2,2])
  def rejected(words,maskwords=9):
   sentinel=b'\xa6'*64;data(0xa00041000,sentinel)
   wr(0x1b802100,1);wr(0x1b802104,3);wr(0x1b802110,0x10)
   for i,v in enumerate((words+[0]*9)[:maskwords]):wr(0x1b802140+i*4,v)
   wr(0x1b802108,1);cmd('clock_step 2000000')
   check('rejected request has no TX success',rd(0x1b802080)==0)
   check('rejected request has no RX result',rd(0x1b802084)==0)
   check('rejected request preserves output',read(0xa00041000,64)==sentinel)
   wr(0x1b802100,0)
   qmp.command('cont') # explicitly resume only this synthetic strict-stop test VM
  rejected([2,3,16,12]) # uninitialized
  for words in ([2,1,0,0x40001000,0x50001000],[2,1,5,0x40001000,0x50001000],
                [2,1,1,0,0x50001000],[2,1,1,0x4003f000,0x50001000],
                [2,1,1,0x40001000,0x50001000,1],[1,1,1,0x40001000,0x50001000]):rejected(words)
  rejected([2,1,1,0x40001000,0x50001000],5)
  request([2,1,1,0x40001000,0x50001000])
  for words in ([2,1,1,0x40001000,0x50001000],[2,3,0,0],[2,3,15,11],
                [2,3,16,16],[2,3,0x30000,0x24000],[2,3,16,12,1],[2,4]):rejected(words)
  request([2,2])
  # Reset after accepted transport submission cancels both future IRQ paths.
  wr(0x1b802100,1);wr(0x1b802104,3);wr(0x1b802110,0x10)
  for i,v in enumerate([2,1,1,0x40001000,0x50001000,0,0,0,0]):wr(0x1b802140+i*4,v)
  wr(0x1b802108,1);wr(0x1b800008,1);cmd('clock_step 2000000')
  check('reset cancels TX',rd(0x1b802080)==0);check('reset cancels RX',rd(0x1b802084)==0)
finally:
 if qmp: qmp.close()
 if stream:stream.close()
 if sock:sock.close()
 if proc:stop_child(proc,None)
 (out/'report.json').write_text(json.dumps(dict(original_firmware_loaded=False,qemu_sha256=hashlib.sha256(options.qemu.read_bytes()).hexdigest(),checks=checks),indent=2)+'\n')
print(len(checks),'checks passed')
