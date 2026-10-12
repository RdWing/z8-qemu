# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Continuous offline controller/sensor input using reference device contracts."""
import json,time
from pathlib import Path
from service_z8_mcu import Peer
from service_serial8 import WritePeer
from z8_global1_boundary_input import Peer as BoundaryPeer
from boot_z8 import key_body
P=Path(__file__).resolve().parent

def run(g,seconds=60,control=None):
 peer=Peer(g,limit_frames=1024,config_reply=True,all_mode_replies=True,bindings=json.loads((P/'peer-bindings.json').read_text()))
 clock=BoundaryPeer(g,33,auxiliary_masked=True);spi8=WritePeer(g);spi9=WritePeer(g,channel=9,wire_bits=9,allow_dummy_rx=True)
 def state(name):return json.loads(g.qmp.command('qom-get',path='/machine',property=name))
 def send_running(body):
  # GDB breakpoint changes require a stopped guest; preserve any peer stop first.
  g.qmp.command('stop');peer.handle();peer.enqueue_external(body,2);g.qmp.command('cont')
 explicit=False;deadline=time.monotonic()+seconds;next_capture=0;phase=0;phase_at=0;nav_index=0;nav_at=None;release_at=None;input_ready=0
 g.qmp.command('cont')
 try:
  while time.monotonic()<deadline and not (control and control.stop.is_set()):
   if 'Z8_UNKNOWN' in g.log():raise RuntimeError('Unmodeled hardware; inspect stderr.log')
   if not g.qmp.command('query-status')['running']:
    handled=peer.handle()
    if not handled and not explicit:raise RuntimeError('Stopped outside known peer observation')
    explicit=False;g.qmp.command('cont');continue
   clock.tick();now=time.monotonic()
   vt=state('runtime-clock-state')['virtual_ns']/1e9
   if release_at is not None and vt>=release_at:
    send_running(key_body());release_at=None;input_ready=vt+.5
   if control and phase>=3 and release_at is None and vt>=input_ready:
    offset=control.next_button()
    if offset is not None:
     body=bytearray(key_body());body[offset]=1;send_running(bytes(body));release_at=vt+.10
     control.mark_sent()
     g.data.setdefault('interactive_inputs',[]).append(dict(offset=offset,virtual_seconds=vt))
   if not control and phase==6 and vt>=nav_at and release_at is None:
    sequence=[('ok-bank',74),('back-bank',35),('down-one',37),('ok-extended',74),('back-extended',35),('half-shutter',7)]
    if nav_index<len(sequence):
     label,offset=sequence[nav_index];body=bytearray(key_body());body[offset]=1
     send_running(bytes(body));release_at=vt+.10
     g.data.setdefault('navigation_inputs',[]).append(dict(label=label,offset=offset,pressed=True,virtual_seconds=vt,before_frame=len(g.data.get('pipeline_samples',[]))))
     print('Navigation input: '+label,flush=True);nav_index+=1;nav_at=vt+3
    else:phase=7
   if now>=next_capture:
    g.qmp.command('stop');peer.handle()
    raw=state('raw-pipeline-state');lcd=state('engine1548-scanout-state');vt=state('runtime-clock-state')['virtual_ns']/1e9
    row=dict(raw=raw,lcd=lcd,virtual_seconds=vt,phase=phase,ui_control_hex=g.read_bytes(0xa03228fa4,32).hex())
    g.data.setdefault('pipeline_samples',[]).append(row)
    frame=g.out/('current.ppm' if control else f'frame-{len(g.data["pipeline_samples"]):03d}.ppm')
    g.qmp.command('screendump',filename=str(frame))
    if control:
     control.publish(frame,row,ready=phase>=3 and int.from_bytes(bytes.fromhex(row['ui_control_hex'])[4:8],'little')==1)
     if control.ready:phase=5  # Startup MENU retry must never undo a user's later MENU/half-shutter.
     (g.out/'live-status.json').write_text(json.dumps(dict(control.status(),interactive_inputs=g.data.get('interactive_inputs',[])))+'\n')
    if phase==0 and raw['frames']>=8 and lcd.get('frames',0)>=8:
     peer.enqueue_external(key_body(),2);phase=1;phase_at=vt;print('Native frame acknowledgements and LCD scanout observed; releasing half shutter',flush=True)
    elif phase==1 and vt-phase_at>=2:
     peer.enqueue_external(key_body(menu=True),2);phase=2;phase_at=vt;print('Sending MENU',flush=True)
    elif phase==2 and vt-phase_at>=.4:
     peer.enqueue_external(key_body(),2);phase=3;phase_at=vt
    elif not control and phase==3 and vt-phase_at>=3 and int.from_bytes(bytes.fromhex(row['ui_control_hex'])[4:8],'little')==1:
     phase=6;nav_at=vt
     print('Native menu mode confirmed; starting button navigation test',flush=True)
    elif phase==3 and vt-phase_at>=10 and int.from_bytes(bytes.fromhex(row['ui_control_hex'])[4:8],'little')==6:
     peer.enqueue_external(key_body(menu=True),2);phase=4;phase_at=vt;print('Sending second MENU after native transition wait',flush=True)
    elif phase==4 and vt-phase_at>=.4:
     peer.enqueue_external(key_body(),2);phase=5;phase_at=vt
    next_capture=now+(.2 if control else .5);g.qmp.command('cont')
   channels=state('serial-state')
   if peer.clock_if_ready(channels):explicit=True;continue
   spi8.clock_if_ready(channels[8]);spi9.clock_if_ready(channels[9]);time.sleep(.002)
 finally:
  g.qmp.command('stop')
  g.data['final_pipeline']={n:state(n) for n in ['graphics-state','raw-pipeline-state','engine1548-scanout-state','engine1518-state','engine151-control-state','engine1543-control-state','engine1548-source-state']}
  g.qmp.command('screendump',filename=str(g.out/'final.ppm'));peer.close()
