# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Run original Z8 MAIN and EX on the optional native MCU bridge.

No host MCU messages, firmware instruction patches or register redirection.
Board peripherals, sensor data and declared external-ROM inputs are functional
models. This experimental path has separate acceptance from the host-peer run.
"""
from pathlib import Path
import hashlib
import json
import time
import signal
from runtime import arguments, verify
from full_guest import Guest
from rom_inputs import attach
from service_serial8 import WritePeer
from z8_global1_boundary_input import Peer as BoundaryPeer
from control import Control, png_from_ppm

p=arguments(__doc__)
p.add_argument('--port',type=int,help='Loopback read-only native-MCU display, with Stop control')
p.add_argument('--check-only',action='store_true')
p.add_argument('--mcu',type=Path,required=True)
p.add_argument('--mcu-pins',default='',help='Explicit external contacts, e.g. G1=1:G13=1; no inherited Z63 key names')
p.add_argument('--seconds',type=int,default=180)
p.add_argument('--experimental-shared221',action='store_true')
a=p.parse_args()
if not 1<=a.seconds<=3600:p.error('Duration must be 1..3600 seconds')
if ',' in a.mcu_pins:p.error('Use colon-separated MCU contacts')
if a.port is not None and not (a.port==0 or 1024<=a.port<=65535):p.error('Invalid loopback port')
firmware,_=verify(a.firmware);mcu=a.mcu.resolve()
if ',' in str(mcu) or mcu.stat().st_size!=524288 or hashlib.sha256(mcu.read_bytes()).hexdigest()!='8ce129fa3689d1d619f25ba1c44a3a9f1964c76fe77b95adeb4ea912463c8c63':
 p.error('Expected the original Z8 EX03.00 component')
if not a.qemu.is_file() or not a.raw.is_file():p.error('QEMU and RAW paths must exist')
if a.check_only:print('Original Z8 MAIN/EX and runtime paths verified.');raise SystemExit(0)
g=Guest(firmware,a.qemu,a.raw,a.output)
index=g.command.index('-M')+1
g.command[index]=g.command[index].replace('nikon-z8-lab,','nikon-z8-full-lab,zr-sd-empty-fixture=on,')+',mcu-image='+str(mcu)+',mcu-pins='+a.mcu_pins
if a.experimental_shared221:
 profile=json.loads(Path(__file__).with_name('experimental-shared221-profile.json').read_text())
 properties=dict(profile['properties']);properties['ccomp-gpio-model']='off'
 g.command[index]+=','+','.join(k+'='+v for k,v in properties.items())
g.command[g.command.index('-smp')+1]='4,maxcpus=5'
g.command+=['-device',f'loader,file={firmware},addr=0x40160000,force-raw=on,cpu-num=0']
attach(g);g.data.update(command=g.command,native_mcu=True,host_mcu_messages=False,mcu_sha256=hashlib.sha256(mcu.read_bytes()).hexdigest())
control=Control(a.port,native_mcu=True) if a.port is not None else None
if control:
 control.write_endpoint(g.out);signal.signal(signal.SIGTERM,lambda *_:control.stop.set())
try:
 with g:
  g.rsp('z1,40160000,4')
  boundary=BoundaryPeer(g,33,auxiliary_masked=True,auxiliary1_masked=a.experimental_shared221,global0_bit26=a.experimental_shared221)
  spi8=WritePeer(g);spi9=WritePeer(g,channel=9,wire_bits=9,allow_dummy_rx=True)
  deadline=time.monotonic()+a.seconds;next_sample=0
  g.qmp.command('cont')
  while time.monotonic()<deadline and not (control and control.stop.is_set()):
   if not g.qmp.command('query-status')['running'] or 'Z8_UNKNOWN' in g.log():break
   boundary.tick()
   channels=json.loads(g.qmp.command('qom-get',path='/machine',property='serial-state'))
   spi8.clock_if_ready(channels[8]);spi9.clock_if_ready(channels[9])
   now=time.monotonic()
   if now>=next_sample:
    row={name:json.loads(g.qmp.command('qom-get',path='/machine',property=name)) for name in ['native-mcu-state','native-mcu-wire-state','raw-pipeline-state','engine1548-scanout-state','runtime-clock-state']}
    g.data.setdefault('native_samples',[]).append(row)
    if control:
     g.qmp.command('stop');frame=g.out/'current.ppm';g.qmp.command('screendump',filename=str(frame))
     control.publish(frame,dict(raw=row['raw-pipeline-state'],lcd=row['engine1548-scanout-state'],virtual_seconds=row['runtime-clock-state']['virtual_ns']/1e9))
     g.qmp.command('cont')
    (g.out/'native-live.json').write_text(json.dumps(row)+'\n');next_sample=now+.5
   time.sleep(.002)
  g.qmp.command('stop')
  g.qmp.command('memsave',val=0x2000d000,size=7964,filename=str(g.out/'mcu-initialized-data.bin'),**{'cpu-index':4})
  g.data['native_cpus']={str(i):g.qmp.hmp('info registers',i) for i in range(5)}
  g.data['final_native_mcu']=json.loads(g.qmp.command('qom-get',path='/machine',property='native-mcu-state'))
  g.qmp.command('screendump',filename=str(g.out/'final.ppm'))
  (g.out/'final.png').write_bytes(png_from_ppm(g.out/'final.ppm'))
  (g.out/'toplcd-bits.hex').write_text(g.qmp.command('qom-get',path='/machine',property='mcu-toplcd-bits')+'\n')
finally:
 if control:control.close()
 print(g.out)
