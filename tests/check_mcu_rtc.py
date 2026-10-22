#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise RTC flags, EXTI and NVIC through an independent synthetic M4."""
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

M4=r'''
.syntax unified
.cpu cortex-m4
.thumb
.section .text
.word 0x2004fff0
.word 0x08000101
.org (16+3)*4
.word 0x08000801
.org (16+41)*4
.word 0x08000881
.org 0x100
.thumb_func
start:
ldr r7, =0x20001000
ldr r4, =0x40002800
ldr r5, =0x40013c00
ldr r0, [r7, #64]
cmp r0, #1
beq resume
ldr r0, =0xe000e100
movs r1, #8
str r1, [r0]
ldr r1, =0x200
str r1, [r0, #4]
ldr r0, =0x40023870
ldr r1, =0x8101
str r1, [r0]
movs r0, #0xca
str r0, [r4, #0x24]
movs r0, #0x53
str r0, [r4, #0x24]
ldr r0, =0x400000
str r0, [r5]
str r0, [r5, #8]
ldr r0, =0x40000
str r0, [r4, #8]
movs r0, #0
str r0, [r4, #12]
ldr r0, =409
str r0, [r4, #20]
ldr r0, [r4, #40]
str r0, [r7, #56]
ldr r0, =0x40400
str r0, [r4, #8]
flag_wake:
ldr r0, [r4, #12]
tst r0, #0x400
beq flag_wake
str r0, [r7]
ldr r0, [r4, #40]
str r0, [r7, #60]
ldr r0, [r5, #20]
str r0, [r7, #4]
movs r0, #1
str r0, [r7, #16]
wait1:
ldr r0, =0x40020010
ldr r0, [r0]
tst r0, #4
beq wait1
ldr r0, =0x44400
str r0, [r4, #8]
wait_wakes:
ldr r0, [r7, #8]
cmp r0, #3
blo wait_wakes
ldr r0, =0x40000
str r0, [r4, #8]
movs r0, #2
str r0, [r7, #16]
wait2:
ldr r0, =0x40020010
ldr r0, [r0]
tst r0, #4
bne wait2
ldr r0, =0x420000
str r0, [r5, #8]
ldr r0, =0xc1808080
str r0, [r4, #28]
ldr r0, =0x090000ff
str r0, [r4, #68]
movs r0, #0
str r0, [r4, #12]
ldr r0, =0x41100
str r0, [r4, #8]
flag_alarm:
ldr r0, [r4, #12]
tst r0, #0x100
beq flag_alarm
str r0, [r7, #24]
ldr r0, [r5, #20]
str r0, [r7, #28]
movs r0, #3
str r0, [r7, #16]
wait3:
ldr r0, =0x40020010
ldr r0, [r0]
tst r0, #4
beq wait3
ldr r0, =0x420000
str r0, [r5]
wait_alarms:
ldr r0, [r7, #12]
cmp r0, #3
blo wait_alarms
ldr r0, =0x40000
str r0, [r4, #8]
movs r0, #4
str r0, [r7, #16]
wait4:
ldr r0, =0x40020010
ldr r0, [r0]
tst r0, #4
bne wait4
movs r0, #0x80
str r0, [r4, #12]
ldr r0, =0x235959
str r0, [r4]
ldr r0, =0x269231
str r0, [r4, #4]
movs r0, #0
str r0, [r4, #12]
ldr r0, =0x01000000
str r0, [r4, #28]
ldr r0, =0x45000000
str r0, [r4, #32]
movs r0, #0
str r0, [r4, #68]
str r0, [r4, #72]
ldr r0, =0x43300
str r0, [r4, #8]
wait_both:
ldr r0, [r7, #36]
cmp r0, #1
blo wait_both
ldr r0, =0x40000
str r0, [r4, #8]
movs r0, #5
str r0, [r7, #16]
movs r0, #1
str r0, [r7, #64]
ldr r0, =409
str r0, [r4, #20]
ldr r0, =0x44400
str r0, [r4, #8]
ldr r0, =0xe000ed0c
ldr r1, =0x05fa0004
str r1, [r0]
b .
resume:
movs r0, #2
str r0, [r7, #64]
ldr r0, =0xe000e100
movs r1, #8
str r1, [r0]
ldr r0, =0x400000
str r0, [r5]
str r0, [r5, #8]
movs r0, #0xca
str r0, [r4, #0x24]
movs r0, #0x53
str r0, [r4, #0x24]
ldr r0, [r4, #8]
str r0, [r7, #68]
ldr r0, [r4, #20]
str r0, [r7, #72]
wait_retained:
ldr r0, [r7, #8]
cmp r0, #4
blo wait_retained
ldr r0, =0x40000
str r0, [r4, #8]
movs r0, #6
str r0, [r7, #16]
finish:
wfi
b finish
.ltorg
.org 0x800
.thumb_func
wake_irq:
push {r0-r3,lr}
ldr r0, =0x40002800
ldr r1, [r0, #12]
bic r1, r1, #0x400
str r1, [r0, #12]
ldr r0, =0x40013c14
ldr r1, =0x400000
str r1, [r0]
ldr r0, =0x20001000
ldr r1, [r0, #8]
adds r1, #1
str r1, [r0, #8]
pop {r0-r3,pc}
.ltorg
.org 0x880
.thumb_func
alarm_irq:
push {r0-r3,lr}
ldr r0, =0x40002800
ldr r1, [r0, #12]
ldr r2, =0x20001000
str r1, [r2, #52]
tst r1, #0x100
beq no_a
ldr r3, [r2, #12]
adds r3, #1
str r3, [r2, #12]
no_a:
tst r1, #0x200
beq no_b
ldr r3, [r2, #36]
adds r3, #1
str r3, [r2, #36]
no_b:
ldr r3, [r0]
str r3, [r2, #40]
ldr r3, [r0, #4]
str r3, [r2, #44]
bic r1, r1, #0x300
str r1, [r0, #12]
ldr r0, =0x40013c14
ldr r1, =0x20000
str r1, [r0]
pop {r0-r3,pc}
.ltorg
'''


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--qemu',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--clang',default='clang')
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report=dict(original_firmware_loaded=False,qemu_sha256=hashlib.sha256(args.qemu.read_bytes()).hexdigest(),checks=[])
    proc=qmp=None
    def check(name,ok):
        report['checks'].append(dict(name=name,passed=bool(ok)))
        if not ok:raise AssertionError(name)
    def compile(name,source,target,flags=()):
        text=out/(name+'.S');text.write_text(source);obj=out/(name+'.o');binary=out/(name+'.bin')
        subprocess.run([args.clang,'--target='+target,'-c',str(text),'-o',str(obj),*flags],check=True,capture_output=True)
        binary.write_bytes(elf_text(obj.read_bytes()));return binary
    a53=compile('a53',(FIXTURES/'a53-reset-heartbeat.S').read_text(),'aarch64-none-elf')
    mcu=compile('mcu',M4,'arm-none-eabi',('-mcpu=cortex-m4','-mthumb'))
    try:
        with tempfile.TemporaryDirectory(prefix='z8-rtc-') as temp:
            endpoint=Path(temp)/'qmp'
            machine=f'nikon-z8-lab,mcu-image={mcu},mcu-pins=A2=0,bootstrap-fixtures=on,bus-window-fixture=on,serial-fixture=on,image-bank-model=on,statistics-raw='
            command=[str(args.qemu.resolve()),'-M',machine,'-cpu','cortex-a53','-smp','4,maxcpus=5','-kernel',str(a53),'-accel','tcg,thread=single','-icount','shift=6,sleep=off','-display','none','-serial','none','-monitor','none','-nic','none','-S','-no-reboot','-qmp',f'unix:{endpoint},server=on,wait=off']
            with (out/'stderr.log').open('wb') as log:proc=subprocess.Popen(command,stdout=log,stderr=log)
            wait_for_sockets(proc,endpoint);qmp=QMP(endpoint)
            def state():return json.loads(qmp.command('qom-get',path='/machine',property='native-mcu-io-state'))
            def words():
                qmp.command('memsave',val=0x20001000,size=76,filename=str(out/'result.bin'),**{'cpu-index':4})
                return struct.unpack('<19I',(out/'result.bin').read_bytes())
            def advance(phase):
                qmp.command('cont');deadline=time.monotonic()+12
                while True:
                    time.sleep(.02);qmp.command('stop');w=words()
                    if w[4]==phase:return w
                    if time.monotonic()>deadline:raise TimeoutError(f'M4 phase {phase}: {w!r}')
                    qmp.command('cont')
            def run_for(seconds):
                clock=lambda:json.loads(qmp.command('qom-get',path='/machine',property='runtime-clock-state'))['virtual_ns']
                target=clock()+int(seconds*1e9);qmp.command('cont');deadline=time.monotonic()+12
                while True:
                    time.sleep(.02);qmp.command('stop')
                    if clock()>=target:return
                    if time.monotonic()>deadline:raise TimeoutError('virtual RTC interval')
                    qmp.command('cont')
            def level(v):qmp.command('qom-set',path='/machine',property='mcu-pins',value='A2='+str(v))
            w=advance(1);s=state()
            check('WUTE raises WUTF without IE or an EXTI event',w[0]&0x400 and not(w[1]&0x400000) and w[2]==0)
            check('read-only observation preserves flags and counters',s==state())
            check('reload 409 runs on LSE divided by 16',s['rtc']['wakeup_reload']==409 and s['rtc']['wakeup_expiries']>=1 and ((w[14]-w[15])&255) in (51,52,53))
            before_expiries=s['rtc']['wakeup_expiries']
            level(1);w=advance(2);s=state()
            check('enabling IE on a pending flag reaches NVIC3',w[2]==3 and s['rtc']['wakeup_expiries']>=before_expiries+2 and not(s['rtc']['stored_status']&0x400))
            count=s['rtc']['wakeup_expiries'];run_for(.5)
            check('disabling WUTE cancels future expiries',state()['rtc']['wakeup_expiries']==count and words()[2]==3)
            level(0);w=advance(3);s=state()
            check('masked EXTI17 latches alarm without NVIC41',w[6]&0x100 and w[7]&0x20000 and w[3]==0)
            check('native 9-bit subsecond match sets ALRAF',s['rtc']['alarm_matches'][0]>=1 and s['rtc']['alarm_subseconds_a']==0x090000ff)
            level(1);w=advance(4);s=state()
            check('unmasking pending EXTI17 delivers the alarm',w[3]==3 and not(s['rtc']['stored_status']&0x100))
            counts=s['rtc']['alarm_matches'];run_for(1.1)
            check('disabled alarms do not manufacture further events',state()['rtc']['alarm_matches']==counts and words()[3]==3)
            level(0);w=advance(6);s=state()
            check('date and weekday alarms both reach shared NVIC41',w[3]==4 and w[9]==1 and w[13]&0x300==0x300)
            check('calendar alarm crosses midnight and year',w[10]==0 and w[11]==0x27a101)
            check('handlers clear flags and both EXTI pending bits',not(s['rtc']['stored_status']&0x700) and not(s['exti']['pending']&0x420000))
            check('RTC timer/control survive an actual MCU-only reset',w[16]==2 and w[17]&0x4400==0x4400 and w[18]==409 and w[2]==4)
            native=json.loads(qmp.command('qom-get',path='/machine',property='native-mcu-state'))
            check('controller reset count is independent of the A53',native['system_resets']==1)
            qmp.command('pmemsave',val=0xa00010000,size=16,filename=str(out/'a53.bin'))
            heartbeat=struct.unpack('<2Q',(out/'a53.bin').read_bytes())
            check('A53 heartbeat remains live across RTC/controller reset',heartbeat[0]==0x4135334845415254 and heartbeat[1]>0)
            report['final_io']=s;report['words']=list(w)
            stop_child(proc,qmp);qmp=None;check('owned guest reaped',proc.poll() is not None)
    except Exception as error:
        report['error']=repr(error);raise
    finally:
        stop_child(proc,qmp);(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Passed',len(report['checks']),'actual RTC/EXTI/NVIC checks; synthetic programs only')


if __name__=='__main__':main()
