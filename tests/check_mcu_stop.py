#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute independent M4 STOP/WFI/RTC and STOP/WFE/EXTI checks."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import time
from check_mcu_reset import elf_text, FIXTURES
from qemu_control import QMP, stop_child, wait_for_sockets

M4 = r'''
.syntax unified
.cpu cortex-m4
.thumb
.section .text
.word 0x2004fff0
.word 0x08000101
.org 15*4
.word 0x08000801
.org (16+3)*4
.word 0x08000841
.org (16+28)*4
.word 0x08000881
.org 0x100
.thumb_func
start:
ldr r7, =0x20001000
ldr r4, =0x40002800
ldr r5, =0x40013c00
ldr r6, =0xe000ed10
ldr r0, =0xe000e100
ldr r1, =0x10000008
str r1, [r0]
ldr r0, =0x40023870
ldr r1, =0x8101
str r1, [r0]
movs r0, #0xca
str r0, [r4, #0x24]
movs r0, #0x53
str r0, [r4, #0x24]
ldr r0, =8192
str r0, [r4, #20]
ldr r0, =0x400000
str r0, [r5]
str r0, [r5, #8]
ldr r0, =0x44400
str r0, [r4, #8]
ldr r0, =0x40000000
ldr r1, =89
str r1, [r0, #40]
ldr r1, =999
str r1, [r0, #44]
movs r1, #1
str r1, [r0, #12]
str r1, [r0]
ldr r0, =0xe000e010
ldr r1, =179999
str r1, [r0, #4]
movs r1, #0
str r1, [r0, #8]
movs r1, #7
str r1, [r0]
ldr r0, =0x40007000
ldr r1, =0xc001
str r1, [r0]
movs r0, #1
str r0, [r7]
movs r0, #4
str r0, [r6]
ldr r0, [r7, #4]
str r0, [r7, #20]
ldr r0, [r7, #12]
str r0, [r7, #24]
ldr r0, =0x40000024
ldr r0, [r0]
str r0, [r7, #28]
wfi
ldr r0, [r7, #4]
str r0, [r7, #32]
ldr r0, [r7, #12]
str r0, [r7, #36]
ldr r0, =0x40000024
ldr r0, [r0]
str r0, [r7, #40]
ldr r0, [r6]
str r0, [r7, #16]
movs r0, #0
str r0, [r6]
ldr r0, =0x40000
str r0, [r4, #8]
movs r0, #2
str r0, [r7]
wait_host:
ldr r0, =0x40020010
ldr r0, [r0]
tst r0, #4
beq wait_host
movs r0, #0
str r0, [r5]
movs r0, #4
str r0, [r5, #4]
str r0, [r5, #8]
ldr r0, =0x400000
str r0, [r5, #20]
movs r0, #3
str r0, [r7]
movs r0, #4
str r0, [r6]
sev
wfe
wfe
movs r0, #0
str r0, [r6]
movs r0, #4
str r0, [r7]
wfi
movs r0, #5
str r0, [r7]
finish:
wfi
b finish
.ltorg
.org 0x800
.thumb_func
systick_irq:
push {r0-r1,lr}
ldr r0, =0x20001004
ldr r1, [r0]
adds r1, #1
str r1, [r0]
pop {r0-r1,pc}
.ltorg
.org 0x840
.thumb_func
rtc_irq:
push {r0-r1,lr}
ldr r0, =0x40002800
ldr r1, [r0, #12]
bic r1, r1, #0x400
str r1, [r0, #12]
ldr r0, =0x40013c14
ldr r1, =0x400000
str r1, [r0]
ldr r0, =0x20001008
ldr r1, [r0]
adds r1, #1
str r1, [r0]
pop {r0-r1,pc}
.ltorg
.org 0x880
.thumb_func
timer_irq:
push {r0-r1,lr}
ldr r0, =0x40000010
movs r1, #0
str r1, [r0]
ldr r0, =0x2000100c
ldr r1, [r0]
adds r1, #1
str r1, [r0]
pop {r0-r1,pc}
.ltorg
'''


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--qemu',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report=dict(original_firmware_loaded=False,qemu_sha256=hashlib.sha256(args.qemu.read_bytes()).hexdigest(),checks=[])
    proc=qmp=None
    def check(name,ok):
        report['checks'].append(dict(name=name,passed=bool(ok)))
        if not ok:raise AssertionError(name)
    def compile(name,source,target,flags=()):
        text=out/(name+'.S');text.write_text(source);obj=out/(name+'.o');binary=out/(name+'.bin')
        subprocess.run(['clang','--target='+target,'-c',str(text),'-o',str(obj),*flags],check=True,capture_output=True)
        binary.write_bytes(elf_text(obj.read_bytes()));return binary
    a53=compile('a53',(FIXTURES/'a53-reset-heartbeat.S').read_text(),'aarch64-none-elf')
    mcu=compile('mcu',M4,'arm-none-eabi',('-mcpu=cortex-m4','-mthumb'))
    try:
        with tempfile.TemporaryDirectory(prefix='z8-stop-') as temp:
            endpoint=Path(temp)/'qmp'
            machine=f'nikon-z8-lab,mcu-image={mcu},mcu-pins=A2=0,bootstrap-fixtures=on,bus-window-fixture=on,serial-fixture=on,image-bank-model=on,statistics-raw='
            command=[str(args.qemu.resolve()),'-M',machine,'-cpu','cortex-a53','-smp','4,maxcpus=5','-kernel',str(a53),'-accel','tcg,thread=single','-icount','shift=6,sleep=off','-display','none','-serial','none','-monitor','none','-nic','none','-S','-no-reboot','-qmp',f'unix:{endpoint},server=on,wait=off']
            with (out/'stderr.log').open('wb') as log:proc=subprocess.Popen(command,stdout=log,stderr=log)
            wait_for_sockets(proc,endpoint);qmp=QMP(endpoint)
            def io():return json.loads(qmp.command('qom-get',path='/machine',property='native-mcu-io-state'))
            def read(address,size=20):
                qmp.command('memsave',val=address,size=size,filename=str(out/'words.bin'),**{'cpu-index':4})
                return struct.unpack('<'+'I'*(size//4),(out/'words.bin').read_bytes())
            def clock():return json.loads(qmp.command('qom-get',path='/machine',property='runtime-clock-state'))['virtual_ns']
            def advance(predicate):
                deadline=time.monotonic()+15;qmp.command('cont')
                while True:
                    time.sleep(.005);qmp.command('stop')
                    if predicate():return
                    if time.monotonic()>deadline:raise TimeoutError(str((read(0x20001000),io()['power'])))
                    qmp.command('cont')
            advance(lambda:read(0x20001000)[0]==2)
            w=read(0x20001000)
            recorded=read(0x20001014,24)
            check('SLEEPDEEP plus WFI enters STOP',io()['power']['stop_entries']==1)
            check('SysTick and TIM2 do not wake STOP',recorded[0]==recorded[3] and recorded[1]==recorded[4] and clock()>=3_900_000_000)
            check('TIM2 counter does not consume STOP time',(recorded[5]-recorded[2])%1000 < 32)
            check('RTC wakes STOP through EXTI22 and NVIC3',w[2]==1 and io()['power']['stop_wakes']==1)
            check('SLEEPDEEP survives until firmware clears it',w[4]&4)
            qmp.command('qom-set',path='/machine',property='mcu-pins',value='A2=1')
            advance(lambda:io()['power']['stop_active'])
            before=read(0x20001000);at=clock()
            check('SEV WFE WFE enters a second STOP',before[0]==3 and io()['power']['stop_entries']==2)
            advance(lambda:clock()-at>=1_000_000_000)
            check('WFE STOP also gates periodic clocks',read(0x20001000)[1:4]==before[1:4] and io()['power']['stop_active'])
            qmp.command('qom-set',path='/machine',property='mcu-pins',value='A2=0')
            at=clock();advance(lambda:clock()-at>=1_000_000_000)
            check('unselected falling edge does not wake STOP',io()['power']['stop_active'])
            qmp.command('qom-set',path='/machine',property='mcu-pins',value='A2=1')
            advance(lambda:read(0x20001000)[0]==5)
            at=clock();advance(lambda:clock()-at>=10_000_000)
            w=read(0x20001000)
            check('EXTI event wakes WFE without an NVIC interrupt',io()['power']['stop_wakes']==2 and w[2]==1)
            check('ordinary WFI remains ordinary sleep',io()['power']['stop_entries']==2 and w[1]>before[1] and w[3]>before[3])
            report['final_io']=io();report['words']=list(w)
            qmp.command('pmemsave',val=0xa00010000,size=16,filename=str(out/'a53.bin'))
            heartbeat=struct.unpack('<2Q',(out/'a53.bin').read_bytes())
            check('A53 remains live independently',heartbeat[0]==0x4135334845415254 and heartbeat[1]>0)
            stop_child(proc,qmp);qmp=None;check('owned guest reaped',proc.poll() is not None)
    except Exception as error:
        report['error']=repr(error);raise
    finally:
        stop_child(proc,qmp);(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Passed',len(report['checks']),'actual STOP/RTC/EXTI checks; synthetic programs only')


if __name__=='__main__':main()
