# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Continuous offline controller/sensor input using reference device contracts."""
import json,time
from pathlib import Path
from service_z8_mcu import Peer as BasePeer
from capture_peer import Peer
from service_serial8 import WritePeer
from z8_global1_boundary_input import Peer as BoundaryPeer
from boot_z8 import key_body
from mcu_frames import frames
P=Path(__file__).resolve().parent

def run(g,seconds=60,control=None):
 peer=Peer(g,limit_frames=1024,config_reply=True,all_mode_replies=True,bindings=json.loads((P/'peer-bindings.json').read_text()))
 for address,label in [(0x40c036b8,'capture_full_exception'),(0x40c07c24,'capture_full_diagnostic_dump'),(0x40ea0494,'capture_full_completion_target'),(0x40f6eb64,'capture_full_completion_alternate'),(0x40f70070,'capture_full_completion_aux'),(0x40f91df8,'capture_full_prepare_mode'),(0x40f91e00,'capture_full_prepare_kind'),(0x40e98cf4,'capture_full_complete_a'),(0x40e9914c,'capture_full_complete_b'),(0x40e9965c,'capture_full_complete_c'),(0x40e9dac8,'capture_full_complete_d'),(0x40ea048c,'capture_full_complete_e'),(0x410376a0,'capture_full_complete_f'),(0x40f6c2b4,'capture_full_completion_receive'),(0x40f91eb0,'capture_full_prepare_submit'),(0x40f91eb4,'capture_full_prepare_return'),(0x40f926b8,'capture_full_join_bit1'),(0x40f7dc60,'capture_full_join_bit2'),(0x4046c554,'capture_full_busy_write'),(0x40408298,'capture_full_busy_clear'),(0x40fa9d54,'capture_full_ready_producer'),(0x40cc85f0,'rtc_abstract'),(0x40cc8040,'rtc_status'),(0x40fc3958,'rtc_inhibit_clear'),(0x40fd9350,'shutter_callback')]:peer.arm(address,label)
 clock=BoundaryPeer(g,33,auxiliary_masked=True);spi8=WritePeer(g);spi9=WritePeer(g,channel=9,wire_bits=9,allow_dummy_rx=True)
 def state(name):return json.loads(g.qmp.command('qom-get',path='/machine',property=name))
 def send_running(body):
  # GDB breakpoint changes require a stopped guest; preserve any peer stop first.
  g.qmp.command('stop');peer.handle();peer.enqueue_external(body,2);g.qmp.command('cont')
 explicit=False;deadline=time.monotonic()+seconds;next_capture=0;phase=0;phase_at=0;capture_nav=0;capture_nav_done=not bool(g.capture_menu_states) and not g.capture_menu_file;manual_actions=[];nav_index=0;nav_at=None;release_at=None;input_ready=0
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
    row=dict(completion_registry_hex=g.read_bytes(0xa03b83858,24).hex(),release_mode_hex=g.read_bytes(0xa03bc1ea4,4).hex(),release_join_hex=g.read_bytes(0xa03bc2b24,32).hex(),screen_busy=g.read_bytes(0xa032e78a0,1).hex(),raw=raw,lcd=lcd,d980=state('primary-d980-state'),ccomp=state('ccomp-gpio-state'),virtual_seconds=vt,phase=phase,ui_control_hex=g.read_bytes(0xa03228fa4,32).hex())
    g.data.setdefault('pipeline_samples',[]).append(row)
    (g.out/'capture-live.json').write_text(json.dumps({'latest':row,'full_events':g.data.get('capture_full_events',[]),'lookups':g.data.get('capture_lookup',[]),'key_status':g.data.get('key_status_samples',[])})+'\n')
    frame=g.out/('current.ppm' if control else f'frame-{len(g.data["pipeline_samples"]):03d}.ppm')
    g.qmp.command('screendump',filename=str(frame))
    if control:
     control.publish(frame,row,ready=phase>=3 and int.from_bytes(bytes.fromhex(row['ui_control_hex'])[4:8],'little')==1)
     if control.ready:phase=5  # Startup MENU retry must never undo a user's later MENU/half-shutter.
     (g.out/'live-status.json').write_text(json.dumps(dict(control.status(),interactive_inputs=g.data.get('interactive_inputs',[])))+'\n')
    release_ready=(int.from_bytes(bytes.fromhex(row['release_join_hex'])[:4],'little')==3 and row['screen_busy']=='00')
    startup_ready=raw['frames']>=8 or (g.data.get('experimental_preparation_profile') and release_ready)
    if phase==0 and startup_ready and lcd.get('frames',0)>=8:
     peer.enqueue_external(key_body(),2);phase=1;phase_at=vt;print('Original startup readiness and LCD scanout observed; releasing half shutter',flush=True)
    elif phase==1 and vt-phase_at>=2:
     # First establish the actual Z8 QUAL/dial path before any shutter input.
     phase=10;phase_at=vt;g.data['capture_setup_inputs']=[]
     rtc=bytes([1,0,0,0,26,9,10,12,34,56,0,0,0,0])
     peer.pending.append((7,rtc,frames(rtc,family=7)[0]));peer.start_rx();g.data['rtc_fixture']={'family':7,'body_hex':rtc.hex(),'physical_protocol_verified':False}
    elif phase>=10 and phase<18 and vt-phase_at>=1:
     body=bytearray(key_body())
     if phase in range(10,16):body[0x1f]=1
     if phase in range(11,15):body[0x0b]=255
     peer.enqueue_external(bytes(body),2)
     g.data['capture_setup_inputs'].append(dict(phase=phase,body_hex=body.hex(),virtual_seconds=vt))
     print('QUAL setup state',phase,flush=True)
     phase+=1;phase_at=vt
    elif phase==18 and not capture_nav_done and vt-phase_at>=(.10 if capture_nav and g.capture_menu_states[capture_nav-1]['label'].endswith('-press') else .6):
     if g.capture_menu_file:
      from z8_navigation_input import parse_actions,states
      command=json.loads(g.capture_menu_file.read_text());actions=command['actions']
      assert actions[:len(manual_actions)]==manual_actions,'Menu controls must be append-only'
      if len(actions)>len(manual_actions):
       g.capture_menu_states.extend(states(parse_actions(','.join(actions[len(manual_actions):])))[1:]);manual_actions=actions[:]
      if capture_nav==len(g.capture_menu_states):
       capture_nav_done=bool(command.get('capture',False))
       g.qmp.command('cont');next_capture=now+.5
       continue
     entry=g.capture_menu_states[capture_nav]
     peer.enqueue_external(bytes.fromhex(entry['body_hex']),2)
     g.data.setdefault('capture_menu_inputs',[]).append(dict(entry,virtual_seconds=vt,snapshot=frame.name))
     print('Capture menu:',entry['label'],flush=True)
     capture_nav+=1;phase_at=vt
     capture_nav_done=capture_nav==len(g.capture_menu_states) and not g.capture_menu_file
    elif phase>=18 and phase<23 and capture_nav_done and vt-phase_at>=2:
     if phase==18:
      for address,label in [(0x40e836b0,'capture_full_raw_descriptor_source'),(0x40c0e934,'capture_full_raw_side_config'),(0x40fdaa24,'capture_full_latch_gate'),(0x40fdac4c,'capture_full_latch_submit'),(0x40fdac50,'capture_full_latch_result'),(0x40fdacbc,'capture_full_sequence_dispatch'),(0x40fdae98,'capture_full_sequence_initial'),(0x40fdaf28,'capture_full_sequence_next'),(0x40d5d8b4,'capture_full_method_mode'),(0x40d5ac8c,'capture_full_base_mode'),(0x40d50d90,'capture_full_consume'),(0x40fb0740,'capture_full_admission_flag'),(0x40fb079c,'capture_full_admission_pass'),(0x40fda860,'capture_full_commit'),(0x40d57d94,'capture_full_app_case'),(0x40d57dd4,'capture_full_app_guard'),(0x40d58810,'capture_full_app_mode'),(0x40d58844,'capture_full_app_indirect'),(0x40faaf6c,'capture_full_forward'),(0x40faaea8,'capture_full_tail'),(0x40faafa0,'capture_full_policy'),(0x40fab00c,'capture_full_deferred'),(0x40fa98e4,'capture_full_dispatch_guard'),(0x40fa9994,'capture_full_dispatch_state'),(0x40faaa94,'capture_full_dispatch_alternate'),(0x40faab9c,'capture_full_dispatch_ready'),(0x40d271e4,'key_status'),(0x40fd9430,'capture_full_gpio_store'),(0x40fdc9e0,'capture_full_contact_gate'),(0x40fdca14,'capture_full_contact_notify'),(0x40fdc724,'capture_full_notify'),(0x41175e30,'capture_lookup'),(0x40d51948,'capture_full_application'),(0x40fb875c,'capture_full_request'),(0x40fd9e64,'capture_full_backend'),(0x40fd9f30,'capture_full_worker'),(0x40fd9f68,'capture_full_hold_gate'),(0x40fd9f80,'capture_full_worker_gate'),(0x40fd9f84,'capture_full_worker_gate_return')]:peer.arm(address,label)
     g.data['active_contact_phase']=phase
     if phase>=18:
      for address,label in [(0x404623bc,'capture_full_screen_mode'),(0x404623f4,'capture_full_screen_busy'),(0x40462428,'capture_full_screen_filters'),(0x404240dc,'capture_full_screen_action'),(0x403e94bc,'capture_full_ui_key_code'),(0x4043c4d0,'capture_full_ui_screen'),(0x4043c4e0,'capture_full_ui_screen_indirect'),(0x40c00128,'capture_full_ui_controller'),(0x40d2e218,'capture_full_key_ready'),(0x40d2e230,'capture_full_key_inhibit'),(0x40d2e278,'capture_full_key_dispatch'),(0x40d572c4,'capture_full_state_input'),(0x40d5ab84,'capture_full_state_key')]:peer.arm(address,label)
     body=bytearray(key_body());half,full=[(0,0),(1,0),(1,1),(1,0),(0,0)][phase-18]
     body[7]=half;body[8]=full
     g.qmp.command('qom-set',path='/machine',property='capture-gpio-input',value=str(half|(full<<1)))
     peer.enqueue_external(bytes(body),2)
     g.data.setdefault('shutter_inputs',[]).append(dict(phase=phase,half=half,full=full,virtual_seconds=vt))
     print('Shutter input',half,full,flush=True);phase+=1;phase_at=vt
    if phase==23 and vt-phase_at>=g.capture_settle:break
    next_capture=now+(.2 if control else .5);g.qmp.command('cont')
   channels=state('serial-state')
   if peer.clock_if_ready(channels):explicit=True;continue
   spi8.clock_if_ready(channels[8]);spi9.clock_if_ready(channels[9]);time.sleep(.002)
 finally:
  g.qmp.command('stop')
  g.data['final_pipeline']={n:state(n) for n in ['graphics-state','raw-pipeline-state','engine1548-scanout-state','engine1518-state','engine151-control-state','engine1543-control-state','engine1548-source-state']}
  g.data['capture_readiness']={hex(a):g.read_bytes(a,n).hex() for a,n in [(0xa0281cb88,20),(0xa03bc7b38,4),(0xa03bc7620,4),(0xa03bd060c,16)]}
  g.qmp.command('screendump',filename=str(g.out/'final.ppm'));peer.close()
