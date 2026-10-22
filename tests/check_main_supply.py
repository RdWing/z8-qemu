#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check an explicitly selected virtual MAIN supply; no physical pin claim."""
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
.org 0x100
.thumb_func
start:
ldr r7, =0x20001000
ldr r4, =0x40020800
ldr r5, =0x40020400
movs r0, #4
str r0, [r4]
str r0, [r5]
movs r0, #2
str r0, [r4, #24]
str r0, [r4, #24]
movs r0, #1
str r0, [r7]
wait1:
ldr r0, =0x40020010
ldr r0, [r0]
tst r0, #4
beq wait1
movs r0, #2
str r0, [r5, #24]
ldr r0, =0x20000
str r0, [r5, #24]
movs r0, #2
str r0, [r7]
wait2:
ldr r0, =0x40020010
ldr r0, [r0]
tst r0, #4
bne wait2
ldr r0, =0x20000
str r0, [r4, #24]
movs r0, #3
str r0, [r7]
wait3:
ldr r0, =0x40020010
ldr r0, [r0]
tst r0, #4
beq wait3
movs r0, #2
str r0, [r4, #24]
str r0, [r4, #24]
movs r0, #4
str r0, [r7]
wait4:
ldr r0, =0x40020010
ldr r0, [r0]
tst r0, #4
bne wait4
ldr r0, =0x20000
str r0, [r4, #24]
movs r0, #5
str r0, [r7]
wait5:
ldr r0, =0x40020010
ldr r0, [r0]
tst r0, #4
beq wait5
movs r0, #2
str r0, [r4, #24]
movs r0, #6
str r0, [r7]
finish:
b finish
.ltorg
'''


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--qemu',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report=dict(original_firmware_loaded=False,qemu_sha256=hashlib.sha256(args.qemu.read_bytes()).hexdigest(),checks=[])
    def check(name,ok):
        report['checks'].append(dict(name=name,passed=bool(ok)))
        if not ok:raise AssertionError(name)
    def compile(name,source,target,flags=()):
        text=out/(name+'.S');text.write_text(source);obj=out/(name+'.o');binary=out/(name+'.bin')
        subprocess.run(['clang','--target='+target,'-c',str(text),'-o',str(obj),*flags],check=True,capture_output=True)
        binary.write_bytes(elf_text(obj.read_bytes()));return binary
    source=(FIXTURES/'a53-reset-heartbeat.S').read_text().replace('    mov x2, #0','    ldr x3, [x0, #16]\n    add x3, x3, #1\n    str x3, [x0, #16]\n    mov x2, #0')
    a53=compile('a53',source,'aarch64-none-elf');mcu=compile('mcu',M4,'arm-none-eabi',('-mcpu=cortex-m4','-mthumb'))
    proc=qmp=None
    try:
        for enabled in (False,True):
            with tempfile.TemporaryDirectory(prefix='z8-supply-') as temp:
                endpoint=Path(temp)/'qmp'
                machine=f'nikon-z8-lab,mcu-image={mcu},mcu-pins=A2=0,bootstrap-fixtures=on,bus-window-fixture=on,serial-fixture=on,image-bank-model=on,statistics-raw='
                if enabled:machine+=',mcu-main-supply-pin=C1'
                command=[str(args.qemu.resolve()),'-M',machine,'-cpu','cortex-a53','-smp','4,maxcpus=5','-kernel',str(a53),'-accel','tcg,thread=single','-icount','shift=6,sleep=off','-display','none','-serial','none','-monitor','none','-nic','none','-S','-no-reboot','-qmp',f'unix:{endpoint},server=on,wait=off']
                with (out/f'stderr-{enabled}.log').open('wb') as log:proc=subprocess.Popen(command,stdout=log,stderr=log)
                wait_for_sockets(proc,endpoint);qmp=QMP(endpoint)
                def io():return json.loads(qmp.command('qom-get',path='/machine',property='native-mcu-io-state'))
                def clock():return json.loads(qmp.command('qom-get',path='/machine',property='runtime-clock-state'))['virtual_ns']
                def phase():
                    qmp.command('memsave',val=0x20001000,size=4,filename=str(out/'m4-word.bin'),**{'cpu-index':4})
                    return int.from_bytes((out/'m4-word.bin').read_bytes(),'little')
                def heartbeat():
                    qmp.command('pmemsave',val=0xa00010000,size=24,filename=str(out/'a53-words.bin'))
                    return struct.unpack('<3Q',(out/'a53-words.bin').read_bytes())
                def advance(predicate):
                    deadline=time.monotonic()+12;qmp.command('cont')
                    while True:
                        time.sleep(.005);qmp.command('stop')
                        if predicate():return
                        if time.monotonic()>deadline:raise TimeoutError(str((phase(),io()['main_supply'],heartbeat())))
                        qmp.command('cont')
                def run_for(ns):
                    at=clock();advance(lambda:clock()-at>=ns)
                def level(v):qmp.command('qom-set',path='/machine',property='mcu-pins',value='A2='+str(v))
                advance(lambda:phase()==1 and heartbeat()[2]==1)
                check('initial powered fixture boots without a forced reset '+str(enabled),heartbeat()[0]==0x4135334845415254 and io()['main_supply']['resets']==0)
                level(1);advance(lambda:phase()==2)
                check('neighbor output does not cut MAIN '+str(enabled),not io()['main_supply']['off'])
                level(0);advance(lambda:phase()==3);run_for(100_000_000)
                before=heartbeat();run_for(100_000_000);after=heartbeat()
                if not enabled:
                    check('default attachment has no inferred supply connection',after[1]>before[1] and after[2]==1 and not io()['main_supply']['enabled'])
                else:
                    check('selected output stops A53 execution',before==after and io()['main_supply']['off'] and io()['main_supply']['cuts']==1)
                level(1);advance(lambda:phase()==4);run_for(100_000_000)
                check('return uses architectural reset with retained MAIN RAM '+str(enabled),heartbeat()[2]==(2 if enabled else 1))
                if enabled:
                    check('same-level writes do not issue extra resets',io()['main_supply']['resets']==1)
                level(0);advance(lambda:phase()==5);run_for(100_000_000)
                level(1);advance(lambda:phase()==6);run_for(100_000_000)
                check('second cut/return is repeatable '+str(enabled),heartbeat()[2]==(3 if enabled else 1))
                native=json.loads(qmp.command('qom-get',path='/machine',property='native-mcu-state'))
                check('EX continues without controller reset '+str(enabled),native['system_resets']==0 and phase()==6)
                check('power observations are read-only '+str(enabled),io()==io())
                stop_child(proc,qmp);qmp=None;check('owned guest reaped '+str(enabled),proc.poll() is not None);proc=None
        for value in ('C16','C-1','c1','C4294967296','C1:C2'):
            result=subprocess.run([str(args.qemu.resolve()),'-M','nikon-z8-lab,mcu-main-supply-pin='+value,'-display','none'],capture_output=True,timeout=5)
            check('invalid supply pin rejected '+value,result.returncode!=0 and b'mcu-main-supply-pin' in result.stderr)
    except Exception as error:
        report['error']=repr(error);raise
    finally:
        stop_child(proc,qmp);(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Passed',len(report['checks']),'MAIN supply/reset checks; synthetic programs only')


if __name__=='__main__':main()
