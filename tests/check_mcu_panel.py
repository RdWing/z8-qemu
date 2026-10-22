#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check Z8 panel-ready routing with synthetic A53/M4 guest instructions."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import time
from check_mcu_reset import elf_text,FIXTURES
from qemu_control import QMP,stop_child,wait_for_sockets

M4='''
.syntax unified
.cpu cortex-m4
.thumb
.section .text
.word 0x2004fff0
.word 0x08000081
.org 0x5c
.word 0x08000401
.org 0x80
.thumb_func
start:
ldr r7, =0x20001000
ldr r4, =0x40020000
movs r0, #4
str r0, [r4, #12]
ldr r0, [r4, #16]
str r0, [r7]
ldr r5, =0x40020c00
ldr r0, =0x00400004
str r0, [r5]
movs r0, #2
str r0, [r5, #24]
ldr r6, =0x40013c00
movs r0, #2
str r0, [r6]
str r0, [r6, #8]
str r0, [r6, #20]
ldr r0, =0xe000e100
movs r1, #128
str r1, [r0]
ldr r0, =0x800
str r0, [r5, #24]
ldr r0, [r4, #16]
str r0, [r7, #4]
ldr r0, [r5, #20]
str r0, [r7, #8]
ldr r0, =0x08000000
str r0, [r5, #24]
wait:
ldr r0, [r7, #12]
cmp r0, #0
beq wait
ldr r0, [r4, #16]
str r0, [r7, #20]
/* GPIO A4/E8 and SPI2 are the actual production panel boundary. */
ldr r0, =0x100
str r0, [r4]
ldr r2, =0x40021000
ldr r0, =0x10000
str r0, [r2]
ldr r0, =0x100
str r0, [r2, #24]
ldr r6, =0x40003800
movs r0, #0x40
str r0, [r6]
/* Clear packet. */
movs r0, #16
str r0, [r4, #24]
movs r0, #0x20
strh r0, [r6, #12]
movs r0, #0
strh r0, [r6, #12]
ldr r0, =0x100000
str r0, [r4, #24]
/* Complete line 1: first pixel black, all other pixels white. */
movs r0, #16
str r0, [r4, #24]
movs r0, #0x80
strh r0, [r6, #12]
strh r0, [r6, #12]
movs r0, #0x7f
strh r0, [r6, #12]
movs r1, #17
movs r0, #255
line:
strh r0, [r6, #12]
subs r1, #1
bne line
movs r0, #0
strh r0, [r6, #12]
strh r0, [r6, #12]
ldr r0, =0x100000
str r0, [r4, #24]
/* Complete far-edge line 168, including its eighteenth data byte. */
movs r0, #16
str r0, [r4, #24]
movs r0, #0x80
strh r0, [r6, #12]
movs r0, #0x15
strh r0, [r6, #12]
movs r1, #17
movs r0, #255
last_line:
strh r0, [r6, #12]
subs r1, #1
bne last_line
movs r0, #0xfe
strh r0, [r6, #12]
movs r0, #0
strh r0, [r6, #12]
strh r0, [r6, #12]
ldr r0, =0x100000
str r0, [r4, #24]
/* Incomplete line 2 must not replace any retained pixels. */
movs r0, #16
str r0, [r4, #24]
movs r0, #0x80
strh r0, [r6, #12]
movs r0, #0x40
strh r0, [r6, #12]
movs r1, #7
movs r0, #0
partial:
strh r0, [r6, #12]
subs r1, #1
bne partial
ldr r0, =0x100000
str r0, [r4, #24]
/* Invalid gate 255 and an unselected byte must not write memory. */
movs r0, #16
str r0, [r4, #24]
movs r0, #0x80
strh r0, [r6, #12]
movs r0, #255
strh r0, [r6, #12]
ldr r0, =0x100000
str r0, [r4, #24]
movs r0, #0
strh r0, [r6, #12]
ldr r0, =0x600d600d
str r0, [r7, #24]
1: wfi
b 1b
.ltorg
.org 0x400
.thumb_func
irq:
push {r0,r1,r2,lr}
ldr r0, =0x20001000
ldr r1, [r0, #12]
adds r1, #1
str r1, [r0, #12]
ldr r2, =0x40013c14
ldr r1, [r2]
str r1, [r0, #16]
movs r1, #2
str r1, [r2]
pop {r0,r1,r2,pc}
.ltorg
'''


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--qemu',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--clang',default='clang');a=p.parse_args()
    out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report=dict(original_firmware_loaded=False,qemu_sha256=hashlib.sha256(a.qemu.read_bytes()).hexdigest(),checks=[])
    proc=qmp=None
    def check(name,value):
        report['checks'].append(dict(name=name,passed=bool(value)))
        if not value:raise AssertionError(name)
    def compile(name,text,target,flags=()):
        source=out/(name+'.S');source.write_text(text);obj=out/(name+'.o');binary=out/(name+'.bin')
        subprocess.run([a.clang,'--target='+target,'-c',str(source),'-o',str(obj),*flags],check=True,capture_output=True)
        binary.write_bytes(elf_text(obj.read_bytes()));return binary
    a53=compile('a53',(FIXTURES/'a53-reset-heartbeat.S').read_text(),'aarch64-none-elf')
    mcu=compile('mcu',M4,'arm-none-eabi',('-mcpu=cortex-m4','-mthumb'))
    try:
        with tempfile.TemporaryDirectory(prefix='z8-panel-') as temp:
            endpoint=Path(temp)/'qmp'
            command=[str(a.qemu.resolve()),'-M',f'nikon-z8-lab,mcu-image={mcu},bootstrap-fixtures=on,bus-window-fixture=on,serial-fixture=on,image-bank-model=on',
                '-cpu','cortex-a53','-smp','4,maxcpus=5','-kernel',str(a53),'-accel','tcg,thread=single',
                '-display','none','-serial','none','-monitor','none','-nic','none','-S','-no-reboot','-qmp',f'unix:{endpoint},server=on,wait=off']
            with (out/'stderr.log').open('wb') as log:proc=subprocess.Popen(command,stdout=log,stderr=log)
            wait_for_sockets(proc,endpoint);qmp=QMP(endpoint)
            def panel():return json.loads(qmp.command('qom-get',path='/machine',property='native-mcu-panel-state'))
            cold=panel();check('Z8 ready binding is PA1',cold['ready_port']==0 and cold['ready_pin']==1)
            check('no ready timer or panel transfer before guest action',not cold['ready_pending'] and cold['packets']==cold['lines']==0)
            qmp.command('cont');deadline=time.monotonic()+5
            while True:
                time.sleep(.01);qmp.command('stop');qmp.command('memsave',val=0x20001000,size=28,filename=str(out/'mcu-state.bin'),**{'cpu-index':4})
                words=struct.unpack('<7I',(out/'mcu-state.bin').read_bytes())
                if words[6]==0x600d600d:break
                if time.monotonic()>deadline:raise TimeoutError('Synthetic PA1 ready interrupt did not arrive')
                qmp.command('cont')
            check('PA1 starts at pull-up level',words[0]&2)
            check('PD11 start drives PA1 low',not words[1]&2)
            check('unrelated PD1 output remains high',words[2]&2)
            check('PA1 release delivers exactly one EXTI1 interrupt',words[3]==1 and words[4]&2)
            check('PA1 returns high after ready delay',words[5]&2)
            state=panel();check('ready model remains declared and timer drains',state['ready_delay_ns']==5000000 and state['ready_level']==1 and not state['ready_pending'] and not state['physical_timing_verified'])
            check('complete SPI2 row and clear counted',state['width']==144 and state['height']==168 and state['packets']==5 and state['lines']==2 and state['clears']==1 and state['display_on'])
            bits=qmp.command('qom-get',path='/machine',property='mcu-toplcd-bits')
            check('row order and partial/invalid/select controls preserve memory',bits=='7f'+'ff'*3022+'fe')
            check('repeated panel observation has no side effects',panel()==state and qmp.command('qom-get',path='/machine',property='mcu-toplcd-bits')==bits)
            import sys
            sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
            from panel import png
            (out/'panel.png').write_bytes(png(bits,state['display_on']))
            qmp.command('pmemsave',val=0xa00010000,size=16,filename=str(out/'a53-state.bin'))
            heartbeat=struct.unpack('<2Q',(out/'a53-state.bin').read_bytes());check('A53 advances independently',heartbeat[0]==0x4135334845415254 and heartbeat[1]>0)
            report['panel_state']=state;report['mcu_words']=list(words)
            stop_child(proc,qmp);qmp=None;check('owned guest stopped',proc.poll() is not None)
    except Exception as error:report['error']=repr(error);raise
    finally:stop_child(proc,qmp);(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Passed',len(report['checks']),'actual panel routing checks; synthetic programs only')


if __name__=='__main__':main()
