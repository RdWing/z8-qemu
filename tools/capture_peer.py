# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Bounded external CCOMP ACK experiment; physical Z8 MCU behavior unverified."""
from service_z8_mcu import Peer as BasePeer
from ccomp_command_peer import queue_reply
class Peer(BasePeer):
 def queue_reply(self,wire):
  if queue_reply(self,wire):return
  super().queue_reply(wire)
 def handle(self):
  import re
  lookup_pc=None
  key_pc=None
  busy_pc=None
  follow_target=None
  controller_target=None
  for cpu in range(4):
   regs={k:int(v,16) for k,v in re.findall(r'\b(X\d\d|PC|SP)=([0-9a-fA-F]+)',self.g.qmp.hmp('info registers',cpu))}
   if regs['PC'] in (0x4046c554,0x4046c558) and regs['PC'] in self.points:busy_pc=regs['PC']
   if regs['PC']==0x40c00128 and regs['PC'] in self.points:
    controller_target=regs['X02']
    assert 0x40160000<=controller_target<0x42560000 and controller_target%4==0
   if regs['PC']==0x40d58844 and regs['PC'] in self.points:
    follow_target=regs['X08']
    assert 0x40160000<=follow_target<0x42560000 and follow_target%4==0
   if regs['PC'] in (0x40d271e4,0x40d271e8) and regs['PC'] in self.points:
    key_pc=regs['PC']
    if key_pc==0x40d271e4:
     pointer=regs['X00'];assert 0xa00000000<=pointer<0xa20000000-44
     self.g.data.setdefault('key_status_samples',[]).append({'cpu':cpu,'status_hex':self.g.read_bytes(pointer,44).hex()})
   if regs['PC'] in self.points and regs['PC'] in (0x40e836b0,0x40c0e934):
    address=regs['X08'] if regs['PC']==0x40e836b0 else regs['X01']
    if 0xa00000000<=address<0xa20000000-128:
     self.g.data.setdefault('raw_descriptor_sources',[]).append({'pc':hex(regs['PC']),'address':hex(address),'bytes_hex':self.g.read_bytes(address,128).hex(),'registers':{k:hex(v) for k,v in regs.items()}})
   if regs['PC'] in self.points and self.points[regs['PC']].startswith('capture_full'):
    self.g.data.setdefault('capture_full_events',[]).append({'contact_phase':self.g.data.get('active_contact_phase'),'label':self.points[regs['PC']],'cpu':cpu,'registers':{k:hex(v) for k,v in regs.items()},'fault_context_hex':self.g.read_bytes(regs['X19'],512).hex() if self.points[regs['PC']]=='capture_full_exception' and 0xa00000000<=regs['X19']<0xa20000000-512 else None,'stack_hex':self.g.read_bytes(regs['SP'],2048).hex() if self.points[regs['PC']]=='capture_full_diagnostic_dump' else None,'hold_hex':self.g.read_bytes(0xa03bd060c,16).hex(),'contact_state_hex':self.g.read_bytes(0xa03bd05b0,256).hex(),'notify_registry_hex':self.g.read_bytes(0xa03bd0518,64).hex(),'capture_state_hex':self.g.read_bytes(0xa03bc80a0,128).hex(),'upper_callbacks_hex':self.g.read_bytes(0xa03bc75d8,48).hex()})
   if regs['PC'] in (0x41175e30,0x41175e34) and regs['PC'] in self.points:lookup_pc=regs['PC']
   if regs['PC']==0x41175e30 and regs['PC'] in self.points:
    base=regs['X09'];address=regs['X08']+regs['X10']
    row={'cpu':cpu,'registers':{k:hex(v) for k,v in regs.items()}}
    if 0xa00000000<=base<=0xa20000000-0xf2000 and 0<=address-base-0xdaf40<32:
     row.update(selector=address-base-0xdaf40,index=self.g.read_bytes(address,1).hex(),table_window=self.g.read_bytes(base+0xdaf40,64).hex())
    self.g.data.setdefault('capture_lookup',[]).append(row)
  result=super().handle()
  if busy_pc is not None and len([r for r in self.g.data.get('capture_full_events',[]) if r['label']=='capture_full_busy_write'])<32:self.arm(0x4046c558 if busy_pc==0x4046c554 else 0x4046c554,'busy_write_after' if busy_pc==0x4046c554 else 'capture_full_busy_write')
  if controller_target is not None:self.arm(controller_target,'capture_full_ui_controller_target')
  if follow_target is not None:self.arm(follow_target,'capture_full_app_selected_handler')
  if lookup_pc is not None and len(self.g.data.get('capture_lookup',[]))<32:
   self.arm(0x41175e34 if lookup_pc==0x41175e30 else 0x41175e30,'capture_lookup_after' if lookup_pc==0x41175e30 else 'capture_lookup')
  if key_pc is not None and len(self.g.data.get('key_status_samples',[]))<32:
   self.arm(0x40d271e8 if key_pc==0x40d271e4 else 0x40d271e4,'key_status_after' if key_pc==0x40d271e4 else 'key_status')
  return result
