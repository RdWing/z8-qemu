#!/usr/bin/env python3
# Copyright (C) 2026 RdWing: Z8 adaptation.
"""Check the supplemental models through the actual Z8 MMIO front end.

Synthetic inputs only; no original firmware, R3D profile or recording claim.
"""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
from qemu_control import QMP,stop_child,wait_for_sockets


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--qemu',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    bios=out/'synthetic-a53.bin';bios.write_bytes(bytes.fromhex('00000014'))
    raw=out/'synthetic.raw'
    raw.write_bytes(struct.pack('<8s6I',b'NZ9RAW1\0',64,24,14,0,0,16383)+bytes(64*24*2))
    props=','.join(['bootstrap-fixtures=on','capture-frame-pool-model=on',
        'event1508-channel-model=on','event1508-timing-model=on',
        'event1508-programmed-clock-model=on','video-raw-he-codec-model=on',
        'yuvcmp-config-model=on','yuvcmp-channels-model=on','yuvcmp-channel-ready-model=on','wave5-vpu-model=on','dsp-boot-mailbox-model=on','task1500-control-model=on','video-peripheral-control-model=on','task1500-ff-clear-model=on','image-bank-model=on','dsp-ram-aperture-fixture=on','bus-window-fixture=on'])
    baseline=json.loads((Path(__file__).resolve().parents[1]/'tools/model-properties.json').read_text())
    values=dict(item.split('=',1) for item in baseline['properties'])
    values.update(item.split('=',1) for item in props.split(','))
    values['service-core-event-model']='off'
    values.update({k:'on' for k in json.loads((Path(__file__).resolve().parents[1]/'tools/capture-model-options.json').read_text())})
    values['capture-stream-rearm-model']='on'
    props=','.join(k+'='+v for k,v in values.items())
    q=proc=sock=stream=None
    report={'original_firmware_loaded':False,'qemu_sha256':hashlib.sha256(args.qemu.read_bytes()).hexdigest(),'checks':[]}
    try:
        with tempfile.TemporaryDirectory(prefix='z8-shared221-') as temp:
            endpoint=Path(temp)/'qmp';qt=Path(temp)/'qtest'
            cmd=[str(args.qemu.resolve()),'-M','nikon-z8-lab,'+props+',statistics-raw='+str(raw),
                 '-cpu','cortex-a53','-smp','4','-m','512M','-kernel',str(bios),'-accel','qtest',
                 '-display','none','-serial','none','-monitor','none','-nic','none',
                 '-qmp',f'unix:{endpoint},server=on,wait=off','-qtest',f'unix:{qt},server=on,wait=off']
            with (out/'qemu.log').open('wb') as log, (out/'uart-tx.log').open('xb') as uart:
                proc=subprocess.Popen(cmd,stdout=uart,stderr=log)
            wait_for_sockets(proc,endpoint,qt);q=QMP(endpoint)
            sock=socket.socket(socket.AF_UNIX);sock.settimeout(3);sock.connect(str(qt));stream=sock.makefile('rwb',buffering=0)
            def mmio(cmd):
                stream.write(cmd.encode()+b'\n')
                while True:
                    reply=stream.readline().decode().strip()
                    if reply.startswith('IRQ '):continue
                    if not reply.startswith('OK'):raise RuntimeError(reply)
                    return reply.split()[1:]
            def read(a):return int(mmio(f'readl {a:#x}')[0],0)
            def write(a,v):mmio(f'writel {a:#x} {v:#x}')
            def state(name):return json.loads(q.command('qom-get',path='/machine',property=name))
            def verify(name,value):
                report['checks'].append({'name':name,'pass':bool(value)})
                assert value,name
            # The production board already emits byte TX on stdout. Exercise
            # all four retained banks without loading firmware or fabricating RX.
            for channel, byte in enumerate(b'Z8!\n'):
                write(0x0f000004+16*channel,byte)
            verify('MAIN UART TX preserves combined channel bytes',
                   (out/'uart-tx.log').read_bytes()==b'Z8!\n')
            verify('UART TX is not mixed into QEMU diagnostics',b'Z8!\n' not in (out/'qemu.log').read_bytes())
            verify('UART remains TX empty with no RX producer',
                   all(int(mmio(f'readb {0x0f000003+16*c:#x}')[0],0)==2 for c in range(4)))
            verify('functional HE switch present',q.command('qom-get',path='/machine',property='video-raw-he-codec-model') is True)
            verify('empty capture pool',state('capture-frame-pool-state')['productions']==0)
            write(0x15000304,0xff)
            task=state('task1500-control-state')
            verify('Z8 native task status clear admitted',
                   task['status_clears']==1 and task['status_clear_seen']==4 and read(0x15000304)==0)
            write(0x15000304,0)
            task=state('task1500-control-state')
            verify('task clear does not execute or complete work',
                   task['status_clears']==2 and task['starts']==0 and task['active']==0 and
                   task['pixel_bytes']==0 and task['completion_events']==0)
            # These two words share the board's CPU-release window.
            # Select/commit/poll must reach the video model without changing
            # the separate CPU status and reset-word ownership.
            cpu_status=read(0x0d154044)
            write(0x0d154150,7);write(0x0d154030,1)
            verify('video domain command crosses board MMIO window',
                   read(0x0d154030)==1 and read(0x0d154030)==0 and
                   read(0x0d154150)==7)
            control=state('video-peripheral-control-state')
            verify('video command retains CPU release ownership',
                   control['commands']==1 and control['latched']==7 and
                   not control['pending'] and read(0x0d154044)==cpu_status and
                   control['pixel_bytes']==0 and control['irq_events']==0)
            write(0x15649000,1)
            verify('native YUV channel arm reports ready without work',read(0x15649000)==2 and read(0x15649020)==0)
            yuv=state('yuvcmp-config-state')
            verify('YUV readiness creates no DMA or completion',yuv['arms']==1 and yuv['jobs']==0 and yuv['pixel_bytes']==0 and yuv['completion_events']==0)
            write(0x15649000,0)
            verify('YUV channel disarm retires readiness',read(0x15649000)==0)
            verify('programmed clock available',state('event1508-programmed-clock-state')['enabled'])
            verify('Wave5 compatible identity',read(0x16011044)==0x5210)
            verify('Wave5 authored profile identity',read(0x16011040)==0x574c3556)
            write(0x16010050,1)
            verify('Wave5 reset reaches device',read(0x16010050)==1 and not state('wave5-vpu-state')['booted'])
            # Upload only synthetic nonzero bytes to board-owned DSP load RAM.
            # Boot guard must read that mapping, not an uninitialized donor RAM object.
            for base,program in [(0x1c800000,0x1c200000),(0x1d800000,0x1d200000),(0x1fc00000,0x1f200000)]:
                write(program,0x12345678);write(base+0x28,1);write(base+0x24,1);write(base+0x28,0)
            mmio('clock_step 10000000')
            dsp=state('dsp-boot-mailbox-state');report['dsp']=dsp
            verify('three functional DSP boots',all(r['booted'] for r in dsp['channels']))
            for name in ['video-raw-he-codec-model','capture-frame-pool-model','event1508-programmed-clock-model']:
                rejected=False
                try:q.command('qom-set',path='/machine',property=name,value=False)
                except RuntimeError:rejected=True
                verify(name+' immutable after attachment',rejected)
            verify('synthetic MMIO does not stop VM',q.command('query-status')['running'])
    finally:
        stop_child(proc,q)
        if stream:stream.close()
        if sock:sock.close()
        (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f"{len(report['checks'])} shared221 MMIO checks passed")

if __name__=='__main__':main()
