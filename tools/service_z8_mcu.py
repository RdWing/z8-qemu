# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Continuous diagnostic Z8 MCU peer on the observed channel0/1 PIO path.

GPIO levels and explicit IRQ57/58 assertions follow native instruction
boundaries. Normal FIFO clocks only; no firmware, RAM, register or OS flag
patches. Replies cover the function-validated lens chain and mode8 request.
Physical GPIO/MCU timing and actual lens presence remain unverified.
"""
import json
from pathlib import Path
import re
import struct

from mcu_frames import frames
from probe import sha
from probe_graphics_image import save


class Peer:
    def __init__(self,g,*,limit_frames=256,lens_status_reply=False,config_reply=False,all_mode_replies=False,
                 bindings=None):
        if limit_frames not in (256,512,1024):raise ValueError('explicit supported MCU frame bound required')
        self.g=g
        self.bindings=bindings
        self.points={}
        self.tx=None
        self.rx=None
        self.rx_retiring=False
        self.pending=[]
        self.asserted=set()
        self.lens_status_reply=bool(lens_status_reply)
        self.config_reply=bool(config_reply)
        self.all_mode_replies=bool(all_mode_replies)
        self.expected_modes=[]
        self.record=dict(source_sha256=sha(Path(__file__)),
            classification='diagnostic_continuous_external_MCU_peer',
            physical_protocol_verified=False,camera_acceptance=False,
            cpu_register_redirection=False,ram_patches=[],tx=[],rx=[],events=[],limit_frames=limit_frames,
            lens_status_reply='synthetic_zero_type85' if self.lens_status_reply else 'none',lens_status_consumers=[],
            config_reply='synthetic_zero_type5' if self.config_reply else 'none',config_requests=[],config_consumers=[],
            mode_reply_scope='all_original_valid_modes' if self.all_mode_replies else 'mode8_only',
            mode_requests=[],mode_consumers=[])
        g.data['continuous_mcu_peer']=self.record
        if bindings is not None:
            self.record['instruction_bindings']={k:hex(v) for k,v in bindings.items()}
            self.record['binding_scope']='explicit model-specific static candidates; native stages checked separately'
        self.rx_clear_pc=bindings.get('rx_after_flag_clear') if bindings is not None else 0x40c94164
        self.record['next_rx_scope']='after_original_flag_clear_and_ack' if self.rx_clear_pc else 'after_frame_validation'
        (g.out/'continuous-mcu-peer-source.py').write_bytes(Path(__file__).read_bytes())
        children=g.qmp.command('qom-list',path='/machine/unattached')
        gics=[c for c in children if c['type']=='child<arm-gicv3>']
        if len(gics)!=1:raise ValueError('unique modeled GIC required')
        self.gic='/machine/unattached/'+gics[0]['name']
        names={c['name'] for c in g.qmp.command('qom-list',path=self.gic)}
        if not all(f'unnamed-gpio-in[{n}]' in names for n in (25,26)):
            raise ValueError('observed GPIO IRQ inputs absent')
        self.record['gpio_before']={hex(a):g.rd(a) for a in (0xd15100c,0xd151010)}
        g.wr(0xd151010,g.rd(0xd151010)&~8)
        g.wr(0xd15100c,(g.rd(0xd15100c)|4)&~8)
        self.arm(self.pc(0x40c93c48),'tx_request')
        self.raise_irq(25)

    def pc(self,original):
        if self.bindings is None:return original
        names={0x40c93c48:'tx_request',0x40c160d8:'gpio_tx_isr',0x40c160f0:'gpio_rx_isr',
            0x40c93c4c:'tx_return',0x40c93d34:'tx_ack_read',0x40c93d9c:'tx_finished',
            0x40c94124:'rx_accepted',0x40c94010:'rx_request',0x41181e34:'mode_reply_consumer',
            0x411862dc:'lens_status_consumer',0x41181df0:'config_reply_consumer'}
        return self.bindings[names[original]]

    def address(self,name,original):
        return original if self.bindings is None else self.bindings[name]

    def arm(self,pc,label):
        if pc in self.points:
            if self.points[pc]!=label:raise ValueError('ambiguous MCU observer')
            return
        self.points[pc]=label
        self.g.rsp(f'Z1,{pc:x},4')

    def raise_irq(self,index):
        if index in self.asserted:raise ValueError('MCU IRQ already asserted')
        self.arm(self.pc(0x40c160d8 if index==25 else 0x40c160f0),'tx_gpio_isr' if index==25 else 'rx_gpio_isr')
        self.g.qt_command(f'set_irq_in {self.gic} unnamed-gpio-in {index} 1')
        self.asserted.add(index)
        self.record['events'].append(dict(irq=index+32,level=1))

    def lower_irq(self,index):
        self.g.qt_command(f'set_irq_in {self.gic} unnamed-gpio-in {index} 0')
        self.asserted.remove(index)
        self.record['events'].append(dict(irq=index+32,level=0))

    def disarm(self,pc,label,cpu_hits):
        command=f'z1,{pc:x},4'
        try:
            self.g.rsp(command)
            return True
        except RuntimeError as exc:
            # A CPU snapshot can reach a boundary after QEMU has already
            # retired that global breakpoint. Treat only a verified absent
            # address as an idempotent removal; preserve all other errors.
            if 'E22' not in str(exc):raise
            table=self.g.qmp.hmp('info breakpoints')
            if 'unknown command' in table.lower() or not re.search(r'\b(?:breakpoint|watchpoint)s?\b',table,re.I):
                self.record.setdefault('breakpoint_remove_diagnostics',[]).append(dict(
                    address=hex(pc),label=label,cpu_hits=cpu_hits,reply='E22',
                    qemu_table=table,address_still_present=None,lookup_supported=False))
                raise
            tokens=re.findall(r'(?:0x)?([0-9a-fA-F]{8,16})',table)
            present=any(int(token,16)==pc for token in tokens)
            self.record.setdefault('breakpoint_remove_diagnostics',[]).append(dict(
                address=hex(pc),label=label,cpu_hits=cpu_hits,reply='E22',
                qemu_table=table,address_still_present=present,lookup_supported=True))
            if present:raise
            return False

    def handle(self):
        hits_by_pc={}
        for cpu in range(4):
            text=self.g.qmp.hmp('info registers',cpu)
            regs={k:int(v,16) for k,v in re.findall(r'\b(X\d\d|PC|SP)=([0-9a-fA-F]+)',text)}
            pc=regs['PC']
            if pc in self.points:
                hits_by_pc.setdefault(pc,[]).append((pc,self.points[pc],cpu,regs))
        # QEMU stops the whole SMP guest for a GDB breakpoint. More than one
        # vCPU can consequently report the same PC in this snapshot. A
        # breakpoint is global, so remove and service it once per address;
        # retain the extra CPU observations as evidence rather than sending a
        # second `z1` packet for a breakpoint that has already been removed.
        hits=[]
        for same_pc in hits_by_pc.values():
            first=same_pc[0]
            if len(same_pc)>1:
                first[3]['simultaneous_cpu_hits']=[item[2] for item in same_pc]
            hits.append(first)
        for pc,label,cpu,regs in hits:
            # Each boundary is disarmed before any continuation or later
            # transfer. No persistent stop in a scheduler or polling loop.
            cpu_hits=regs.get('simultaneous_cpu_hits',[cpu])
            breakpoint_removed=self.disarm(pc,label,cpu_hits)
            del self.points[pc]
            event=dict(name=label,cpu=cpu,pc=hex(pc),x0=hex(regs['X00']))
            if not breakpoint_removed:event['breakpoint_already_absent']=True
            if 'simultaneous_cpu_hits' in regs:
                event['simultaneous_cpu_hits']=regs['simultaneous_cpu_hits']
            self.record['events'].append(event)
            if label.endswith('gpio_isr'):
                self.lower_irq(25 if label.startswith('tx') else 26)
            elif label in ('tx_request','rx_request'):
                channel=0 if label=='tx_request' else 1
                self.g.check('continuous MCU request retains original serial channel',regs['X00']==channel)
                raw=save(self.g,f'continuous-{label}-{len(self.record["tx" if channel==0 else "rx"]):03d}',regs['X01'],0x20)
                tx,rx=struct.unpack_from('<QQ',raw)
                expected=save(self.g,f'continuous-{label}-source-{len(self.record["tx" if channel==0 else "rx"]):03d}',tx,256)
                if channel==0:
                    if self.tx is not None:raise ValueError('overlapping native MCU TX')
                    row=dict(index=len(self.record['tx']),descriptor_hex=raw.hex(),expected_hex=expected.hex(),
                        wire_hex='',serial_return=False,ack_read=False,complete=False)
                    self.record['tx'].append(row)
                    self.tx=dict(row=row,wire=b'')
                    self.g.wr(0xd15100c,self.g.rd(0xd15100c)&~4)
                    self.arm(self.pc(0x40c93c4c),'tx_serial_return')
                else:
                    if self.rx is None:raise ValueError('unexpected native MCU RX')
                    self.rx['row'].update(descriptor_hex=raw.hex(),tx_pointer=hex(tx),rx_pointer=hex(rx),expected_tx_hex=expected.hex())
                    self.arm(self.pc(0x40c94124),'rx_frame_accepted')
            elif label=='tx_serial_return':
                self.g.check('continuous native MCU serial TX returns success',regs['X00']==0)
                if self.tx is None or len(self.tx['wire'])!=256:raise ValueError('incomplete MCU TX before ACK')
                self.tx['row']['serial_return']=True
                self.g.wr(0xd151010,self.g.rd(0xd151010)|8)
                self.arm(self.pc(0x40c93d34),'tx_ack_read')
                self.arm(self.pc(0x40c93d9c),'tx_finished')
                self.raise_irq(25)
            elif label=='tx_ack_read':
                self.g.check('continuous native MCU reads ACK high',regs['X00']==1)
                self.tx['row']['ack_read']=True
            elif label=='tx_finished':
                row=self.tx['row']
                self.g.check('continuous MCU TX retires through original driver',row['serial_return'] and row['ack_read'] and
                    self.g.read_bytes(self.address('tx_state',0xa02e9fb88),4)==bytes(4))
                row['complete']=True
                self.queue_reply(self.tx['wire'])
                self.tx=None
                self.g.wr(0xd151010,self.g.rd(0xd151010)&~8)
                if len(self.record['tx'])>=self.record['limit_frames']:raise RuntimeError('bounded MCU TX limit')
                self.arm(self.pc(0x40c93c48),'tx_request')
                if self.rx is not None or self.pending:
                    self.g.wr(0xd15100c,self.g.rd(0xd15100c)&~4)
                    self.start_rx()
                else:
                    self.resume_tx()
            elif label=='rx_frame_accepted':
                row=self.rx['row']
                actual=save(self.g,f'continuous-rx-{row["index"]:03d}-accepted',int(row['rx_pointer'],16),256)
                self.g.check('continuous MCU supplied frame reaches original RX buffer',actual==self.rx['frame'] and self.rx['position']==256)
                self.g.check('continuous RX clocks original TX bytes',self.rx['wire'].hex()==row['expected_tx_hex'])
                row['complete']=True
                self.rx=None
                if self.rx_clear_pc:
                    # The original receiver still clears its old notification
                    # bits after validating the frame. A following IRQ here
                    # can be erased before the receiver reaches its next wait.
                    # Z8 clears flags4/2 at40c94148/154, then acknowledges
                    # GPIO at40c94160. Only after that original boundary may
                    # the peer assert another RX notification. No RAM edits.
                    self.rx_retiring=True
                    self.arm(self.rx_clear_pc,'rx_frame_retired')
                else:
                    self.start_rx()
                    if self.rx is None:self.resume_tx()
            elif label=='rx_frame_retired':
                if self.rx is not None or not self.rx_retiring:
                    raise ValueError('next RX started before original flag clear or retirement absent')
                event['previous_rx_index']=len(self.record['rx'])-1
                self.rx_retiring=False
                self.start_rx()
                if self.rx is None:self.resume_tx()
            elif label=='mode_reply_consumer':
                if not self.expected_modes:raise ValueError('mode consumer has no actual request/reply')
                mode=self.expected_modes.pop(0)
                index=len(self.record['mode_consumers'])
                raw=save(self.g,f'continuous-mode-{index:03d}-abstract',regs['X00'],16)
                pointer=struct.unpack_from('<Q',raw,8)[0]
                payload=save(self.g,f'continuous-mode-{index:03d}-payload',pointer,4)
                row=dict(abstract_hex=raw.hex(),payload_hex=payload.hex(),cpu=cpu,expected_mode=mode)
                self.record['mode_consumers'].append(row)
                if mode==8:self.record['mode_consumer']=row
                self.g.check('continuous mode reply reaches original kind14 matching-mode consumer',
                    raw[0]==14 and payload==struct.pack('<I',mode))
            elif label=='lens_status_consumer':
                index=len(self.record['lens_status_consumers'])
                raw=save(self.g,f'continuous-lens-status-{index:03d}-abstract',regs['X00'],16)
                pointer=struct.unpack_from('<Q',raw,8)[0]
                payload=save(self.g,f'continuous-lens-status-{index:03d}-payload',pointer,20)
                self.record['lens_status_consumers'].append(dict(abstract_hex=raw.hex(),payload_hex=payload.hex(),cpu=cpu))
                self.g.check('synthetic zero type85 reaches original slot4 status dispatch',raw[0]==0x85 and
                    payload[0]==0x85 and payload[2:]==bytes(18))
            elif label=='config_reply_consumer':
                index=len(self.record['config_consumers'])
                raw=save(self.g,f'continuous-config-{index:03d}-abstract',regs['X00'],16)
                pointer=struct.unpack_from('<Q',raw,8)[0]
                payload=save(self.g,f'continuous-config-{index:03d}-payload',pointer,4)
                callback=save(self.g,f'continuous-config-{index:03d}-callback',self.address('config_callback',0xa04c29228),8)
                self.record['config_consumers'].append(dict(abstract_hex=raw.hex(),payload_hex=payload.hex(),
                    callback_hex=callback.hex(),cpu=cpu))
                self.g.check('synthetic zero type5 reaches original kind12 configuration dispatch',
                    raw[0]==12 and payload==bytes(4) and callback!=bytes(8))
        return bool(hits)

    def queue_reply(self,wire):
        family,kind=wire[0],wire[8]
        body=None
        if family==13 and kind in (1,2,3,4):
            body=bytearray(16)
            body[0],body[4]=0x80|kind,wire[12]
        elif self.lens_status_reply and family==13 and kind==5:
            body=bytearray(16)
            body[0],body[4]=0x85,wire[12]
        elif family==1 and kind==8 and struct.unpack_from('<H',wire,2)[0]==5 and wire[12]<12 and (wire[12]==8 or self.all_mode_replies):
            body=bytes([9,0,0,0,wire[12]])
            self.record['mode_requests'].append(dict(index=self.tx['row']['index'],wire_hex=wire.hex(),reply_body_hex=body.hex()))
            if wire[12]==8:
                self.record['mode_request_index']=self.tx['row']['index']
                self.record['mode_request_hex']=wire.hex()
        elif self.config_reply and family==1 and kind==4:
            body=bytes((5,0,0,0,0))
            self.record['config_requests'].append(dict(index=self.tx['row']['index'],wire_hex=wire.hex(),
                reply_body_hex=body.hex()))
        if body is not None:
            self.pending.append((family,bytes(body),frames(body,family=family)[0]))

    def enqueue_external(self,body,family):
        """Serialize an explicit, separately validated external input frame."""
        if family!=2:raise ValueError('only the existing validated key input is accepted here')
        self.pending.append((family,bytes(body),frames(body,family=family)[0]))
        self.start_rx()

    def start_rx(self):
        # An external key may be queued at an observation boundary while the
        # original driver is still waiting for TX ACK. Keep its GPIO handshake
        # intact until tx_finished has retired that frame. The pending input
        # is then started by the existing tx_finished branch.
        if self.tx is not None or self.rx is not None or self.rx_retiring or not self.pending:return
        if len(self.record['rx'])>=self.record['limit_frames']:raise RuntimeError('bounded MCU RX limit')
        family,body,frame=self.pending.pop(0)
        row=dict(index=len(self.record['rx']),family=family,type=body[0],body_hex=body.hex(),frame_hex=frame.hex(),complete=False)
        self.record['rx'].append(row)
        self.rx=dict(row=row,frame=frame,position=0,wire=b'')
        if family==1 and body[0]==9:
            self.expected_modes.append(body[4])
            self.arm(self.pc(0x41181e34),'mode_reply_consumer')
        if family==13 and body[0]==0x85:self.arm(self.pc(0x411862dc),'lens_status_consumer')
        if family==1 and body[0]==5:self.arm(self.pc(0x41181df0),'config_reply_consumer')
        self.arm(self.pc(0x40c94010),'rx_request')
        # Follow the already successful manual TX->reply sequence. Keeping
        # TX-ready high and posting IRQ57 after every ACK can continuously
        # wake the same native MCU task before its RX branch gets to run.
        self.g.wr(0xd15100c,(self.g.rd(0xd15100c)|8)&~4)
        self.raise_irq(26)

    def resume_tx(self):
        if self.rx_retiring:return
        self.g.wr(0xd15100c,self.g.rd(0xd15100c)|4)
        if 25 not in self.asserted:self.raise_irq(25)

    def clock_if_ready(self,channels):
        stopped=False
        for channel,pending in ((0,self.tx),(1,self.rx)):
            if pending is None:continue
            sampled=channels[channel]
            if not sampled['pio_active'] or not sampled['tx_queued'] or sampled['rx_queued']>=64:continue
            g=self.g
            g.qmp.command('stop')
            if 'Z8_UNKNOWN' in g.log():raise RuntimeError('strict device fault before MCU clock')
            stopped=True
            current=json.loads(g.qmp.command('qom-get',path='/machine',property='serial-state'))[channel]
            if current['pio_active'] and current['tx_queued'] and current['rx_queued']<64:
                if current['pio_word_bits']!=16:raise ValueError('MCU peer only covers observed 16-bit PIO')
                position=2*current['clocked']
                count=min(current['tx_queued'],64-current['rx_queued'])
                if position+2*count>256:raise ValueError('MCU FIFO exceeds one transport frame')
                if channel==0:
                    if position!=len(pending['wire']):raise ValueError('MCU TX position differs')
                    incoming=bytes(2*count)
                else:
                    if 'rx_pointer' not in pending['row'] or position!=pending['position']:
                        raise ValueError('MCU RX request/position differs')
                    incoming=pending['frame'][position:position+2*count]
                g.qmp.command('qom-set',path='/machine',property='serial-clock',value=f'{channel}:'+incoming.hex())
                pending['wire']+=bytes.fromhex(g.qmp.command('qom-get',path='/machine',property='serial-last-tx'))
                pending['row']['wire_hex']=pending['wire'].hex()
                if channel==1:
                    pending['position']=position+2*count
                    if pending['position']==256:g.wr(0xd15100c,g.rd(0xd15100c)&~8)
                elif len(pending['wire'])==256:
                    row=pending['row']
                    g.check('continuous MCU TX wire matches original buffer and checksum',
                        row['wire_hex']==row['expected_hex'] and sum(pending['wire'])&255==255)
                    row.update(family=pending['wire'][0],route=pending['wire'][1],type=pending['wire'][8])
        # The service loop must handle ALL observers before resuming this
        # explicit clock stop, including any simultaneous stopped CPUs.
        return stopped

    def close(self):
        self.record['not_observed']=list(self.points.values())
        self.record['pending_replies']=len(self.pending)
        self.record['unconsumed_mode_replies']=self.expected_modes
        for pc in self.points:self.g.rsp(f'z1,{pc:x},4')
        self.points.clear()
        for irq in list(self.asserted):self.lower_irq(irq)
