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
from native_contact_replay import ContactReplay
from native_inputs import Inputs, CONTACTS
import movie_inputs
import native_he
import virtual_card
from native_power import powered_down, validate_supply_pin
import trace_plugin
import native_adc

p=arguments(__doc__)
p.add_argument('--port',type=int,help='Loopback native-MCU display and optional qualified contacts')
p.add_argument('--check-only',action='store_true')
p.add_argument('--mcu',type=Path,required=True)
p.add_argument('--native-controls',action='store_true',help='Qualified EX Menu/navigation/half contacts; requires loopback view')
p.add_argument('--contact-replay',type=Path,help='Ordered original-MCU external contact actions at virtual times')
p.add_argument('--mcu-adc-inputs',help='Declared numeric ADC.CH=VALUE samples; no physical control names')
p.add_argument('--experimental-main-supply-pin',help='Explicit virtual MAIN supply output, e.g. C1; physical wiring unverified, EX/card/RAM retained')
p.add_argument('--mcu-pins',default='',help='Explicit external contacts, e.g. G1=1:G13=1; no inherited Z63 key names')
p.add_argument('--seconds',type=int,default=180)
p.add_argument('--experimental-shared221',action='store_true')
p.add_argument('--card',type=Path,help='Existing virtual exFAT card; guest writes persist')
p.add_argument('--experimental-playback',action='store_true',help='Functional decoder/finite transfer; original EX workflow has separate acceptance')
movie_inputs.arguments(p)
native_he.arguments(p)
trace_plugin.arguments(p)
p.add_argument('--virtual-seconds',type=float,help='Optional finite virtual-time limit; wall duration remains an independent bound')
a=p.parse_args()
try:
 trace_profile=trace_plugin.validate(a)
 if a.experimental_main_supply_pin is not None:validate_supply_pin(a.experimental_main_supply_pin)
 if a.mcu_adc_inputs is not None:native_adc.validate(a.mcu_adc_inputs)
 movie_inputs.validate(a)
 native_capture=native_he.validate(a)
except ValueError as error:p.error(str(error))
if a.card:
 try:a.card=virtual_card.validate(a.card)
 except ValueError as error:p.error(str(error))
if a.experimental_playback and not a.card:p.error('--experimental-playback requires --card')
if a.experimental_playback and not (a.experimental_shared221 and a.experimental_boundary_inputs and a.experimental_sensor_source_clock):
 p.error('Native EX playback requires shared profile, boundary inputs and sensor source clock')
if not 1<=a.seconds<=3600:p.error('Duration must be 1..3600 seconds')
if a.virtual_seconds is not None and not 1<=a.virtual_seconds<=3600:p.error('Virtual duration must be finite within 1..3600 seconds')
if ',' in a.mcu_pins:p.error('Use colon-separated MCU contacts')
if a.native_controls and (a.port is None or a.contact_replay):p.error('--native-controls requires --port and excludes contact replay')
if ',' in str(a.output.resolve()):p.error('Output path cannot contain a comma for EX USART file backends')
if a.port is not None and not (a.port==0 or 1024<=a.port<=65535):p.error('Invalid loopback port')
firmware,_=verify(a.firmware);mcu=a.mcu.resolve()
if ',' in str(mcu) or mcu.stat().st_size!=524288 or hashlib.sha256(mcu.read_bytes()).hexdigest()!='8ce129fa3689d1d619f25ba1c44a3a9f1964c76fe77b95adeb4ea912463c8c63':
 p.error('Expected the original Z8 EX03.00 component')
if not a.qemu.is_file() or not a.raw.is_file():p.error('QEMU and RAW paths must exist')
if a.check_only:print('Original Z8 MAIN/EX and runtime paths verified.');raise SystemExit(0)
contacts=ContactReplay(a.contact_replay) if a.contact_replay else None
if native_capture and a.native_controls:
 contacts=ContactReplay(Path(__file__).with_name('native-he-setup-contacts.json'))
if a.native_controls:a.mcu_pins='G1=1:G13=1:G14=1:G15=1'+(':'+a.mcu_pins if a.mcu_pins else '')
g=Guest(firmware,a.qemu,a.raw,a.output)
trace_plugin.attach(g,trace_profile)
index=g.command.index('-M')+1
g.command[index]=g.command[index].replace('nikon-z8-lab,','nikon-z8-full-lab,zr-sd-empty-fixture=on,')+',mcu-image='+str(mcu)+',mcu-pins='+a.mcu_pins
if a.experimental_main_supply_pin:
 g.command[index]+=',mcu-main-supply-pin='+a.experimental_main_supply_pin
 g.data['experimental_main_supply']=dict(pin=a.experimental_main_supply_pin,active_high=True,initial_powered=True,physical_binding_verified=False,scope='A53/GIC reset; EX, card and RAM retained')
if a.mcu_adc_inputs:
 g.command[index]+=',mcu-adc-inputs='+a.mcu_adc_inputs
 g.data['declared_mcu_adc_inputs']=a.mcu_adc_inputs
if a.experimental_shared221:
 profile=json.loads(Path(__file__).with_name('experimental-shared221-profile.json').read_text())
 properties=dict(profile['properties']);properties['ccomp-gpio-model']='off'
 g.data['experimental_shared221']=dict(profile,effective_properties=properties)
 g.command[index]+=','+','.join(k+'='+v for k,v in properties.items())
g.command[g.command.index('-smp')+1]='4,maxcpus=5'
uart_logs=[]
for channel in range(1,7):
 path=g.out/f'ex-usart{channel}-tx.log'
 g.command+=['-chardev',f'file,id=z8-ex-usart{channel},path={path}']
 uart_logs.append(str(path))
g.data['ex_uart_tx']=dict(paths=uart_logs,receive_supported=False,
 classification='STM32 register-instance output; physical connector and console roles unqualified')
g.command+=['-device',f'loader,file={firmware},addr=0x40160000,force-raw=on,cpu-num=0']
attach(g);movie_inputs.attach(g,a)
if a.card:virtual_card.attach(g,a.card,playback=a.experimental_playback,native_mcu=True)
native_he.attach(g,a)
mode_controls=a.native_controls and native_he.control_modes_enabled(a)
g.data.update(native_mode_controls=mode_controls,native_controls=a.native_controls,native_contact_actions=contacts.actions if contacts else [],command=g.command,native_mcu=True,host_mcu_messages=False,mcu_sha256=hashlib.sha256(mcu.read_bytes()).hexdigest())
control=Control(a.port,playback=a.experimental_playback,native_mcu=True,native_buttons=CONTACTS if a.native_controls else None,native_modes=mode_controls,native_capture=native_capture and a.native_controls,native_dials=a.native_controls) if a.port is not None else None
if control:
 g.startup_cancelled=control.stop.is_set
 control.write_endpoint(g.out);signal.signal(signal.SIGTERM,lambda *_:control.stop.set())
try:
 with g:
  g.rsp('z1,40160000,4')
  inputs=Inputs(g.qmp,allow_modes=mode_controls,allow_capture=native_capture) if a.native_controls else None
  boundary=BoundaryPeer(g,33,auxiliary_masked=True,auxiliary1_masked=a.experimental_boundary_inputs,global0_bit26=a.experimental_boundary_inputs)
  spi8=WritePeer(g);spi9=WritePeer(g,channel=9,wire_bits=9,allow_dummy_rx=True)
  deadline=time.monotonic()+a.seconds;next_sample=0;capture_at=[]
  g.qmp.command('cont')
  while time.monotonic()<deadline and not (control and control.stop.is_set()):
   if 'Z8_UNKNOWN' in g.log():break
   if not g.qmp.command('query-status')['running']:
    g.data['unexpected_native_stop']=True;break
   boundary.tick()
   if inputs and (not contacts or contacts.next==len(contacts.actions)):
    vt=json.loads(g.qmp.command('qom-get',path='/machine',property='runtime-clock-state'))['virtual_ns']/1e9
    event=inputs.tick(control,vt)
    if event:g.data.setdefault('native_interactive_inputs',[]).append(event)
   if contacts:
    vt=json.loads(g.qmp.command('qom-get',path='/machine',property='runtime-clock-state'))['virtual_ns']/1e9
    for event in contacts.dispatch(g.qmp,vt):
     g.data.setdefault('delivered_contacts',[]).append(event);capture_at.append((vt+.7,len(g.data['delivered_contacts'])))
    while capture_at and vt>=capture_at[0][0]:
     _,number=capture_at.pop(0);image=g.out/f'contact-{number:03d}.ppm'
     g.qmp.command('screendump',filename=str(image));image.with_suffix('.png').write_bytes(png_from_ppm(image))
   channels=json.loads(g.qmp.command('qom-get',path='/machine',property='serial-state'))
   spi8.clock_if_ready(channels[8]);spi9.clock_if_ready(channels[9])
   now=time.monotonic()
   if now>=next_sample:
    row={name:json.loads(g.qmp.command('qom-get',path='/machine',property=name)) for name in ['native-mcu-state','native-mcu-panel-state','native-mcu-adc-state','native-mcu-io-state','capture-gpio-state','native-mcu-switch-state','native-mcu-wire-state','raw-pipeline-state','engine1548-scanout-state','runtime-clock-state']}
    row['ui_control_hex']=g.read_bytes(0xa03228fa4,32).hex()
    row['main_switch_cache_hex']=g.read_bytes(0xa0320169c,44).hex()
    native_he.sample(g)
    row['preparing_capture']=bool(native_capture and a.native_controls and contacts and contacts.next<len(contacts.actions))
    if native_capture:
     he=g.data['native_he_models']['engine152c-he-still-state']
     row['capture_completed_jobs']=min(he['jobs'],he['acks'],he['stop_acks'])
     row['capture_ready']=native_he.capture_ready(g,row)
    row['powered_down']=powered_down(row['runtime-clock-state'],int.from_bytes(bytes.fromhex(row['ui_control_hex'])[4:8],'little'))
    if row['powered_down'] and inputs:inputs.release()
    g.data['native_powered_down']=g.data.get('native_powered_down',False) or row['powered_down']
    g.data.setdefault('native_samples',[]).append(row)
    if control:
     g.qmp.command('stop')
     row['native-mcu-panel-state']=json.loads(g.qmp.command('qom-get',path='/machine',property='native-mcu-panel-state'))
     control.publish_panel(g.qmp.command('qom-get',path='/machine',property='mcu-toplcd-bits'),row['native-mcu-panel-state'])
     frame=g.out/'current.ppm';g.qmp.command('screendump',filename=str(frame))
     control.publish(frame,dict(raw=row['raw-pipeline-state'],lcd=row['engine1548-scanout-state'],virtual_seconds=row['runtime-clock-state']['virtual_ns']/1e9,powered_down=row['powered_down'],preparing_capture=row['preparing_capture'],capture_ready=row.get('capture_ready',False),capture_completed_jobs=row.get('capture_completed_jobs',0)),ready=a.native_controls and (row['raw-pipeline-state']['frames']>=8 or (native_capture and int.from_bytes(g.read_bytes(0xa03bc2b24,4),'little')==3)) and int.from_bytes(bytes.fromhex(row['ui_control_hex'])[4:8],'little') in (1,2,6) and row['engine1548-scanout-state']['frames']>=8 and row['native-mcu-switch-state']['frames']>0)
     g.qmp.command('cont')
    (g.out/'native-live.json').write_text(json.dumps(row)+'\n');next_sample=now+.5
    if a.virtual_seconds is not None and row['runtime-clock-state']['virtual_ns']/1e9>=a.virtual_seconds:break
   time.sleep(.002)
  if inputs:inputs.release()
  g.qmp.command('stop')
  g.qmp.command('memsave',val=0x2000d000,size=7964,filename=str(g.out/'mcu-initialized-data.bin'),**{'cpu-index':4})
  # EX boot copies 0x1c4 vector bytes here, then service registration replaces handlers.
  g.qmp.command('memsave',val=0x20000000,size=0x1c4,filename=str(g.out/'mcu-vectors.bin'),**{'cpu-index':4})
  g.data['native_cpus']={str(i):g.qmp.hmp('info registers',i) for i in range(5)}
  if a.experimental_shared221 or a.experimental_playback:
   g.data['native_model_state']={name:json.loads(g.qmp.command('qom-get',path='/machine',property=name)) for name in ['raw-pipeline-state','z8-playback-state','engine15e2-jpeg-state','event1508-channel-state','engine1543-control-state']}
  g.data['final_native_mcu']=json.loads(g.qmp.command('qom-get',path='/machine',property='native-mcu-state'))
  g.qmp.command('screendump',filename=str(g.out/'final.ppm'))
  (g.out/'final.png').write_bytes(png_from_ppm(g.out/'final.ppm'))
  panel_bits=g.qmp.command('qom-get',path='/machine',property='mcu-toplcd-bits')
  (g.out/'toplcd-bits.hex').write_text(panel_bits+'\n')
  panel_state=json.loads(g.qmp.command('qom-get',path='/machine',property='native-mcu-panel-state'))
  g.data['final_native_panel']=panel_state
  import panel
  (g.out/'toplcd.png').write_bytes(panel.png(panel_bits,panel_state['display_on']))
  g.check('native run has no unmodeled MMIO', 'Z8_UNKNOWN' not in g.log())
  g.check('native run has no unexpected stop',not g.data.get('unexpected_native_stop',False))
finally:
 if control:control.close()
 print(g.out)
