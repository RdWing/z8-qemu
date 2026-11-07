#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check the default-off mcu-card-detect semantic alias on the native MCU.

Synthetic A53/M4 programs only: the M4 fixture configures the measured
stock-EX pull pattern (pull-up on B11/C2/F6/G2, floating C5/G14), then
the checks drive each whitelisted card-detect candidate through
mcu-card-detect / mcu-card-detect-pin and read it back through the
EX IDR (native-mcu-io-state). Requires clang with AArch64/Thumb targets.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import time

from check_mcu_reset import elf_text, FIXTURES
from qemu_control import QMP, stop_child, wait_for_sockets

# Dual-evidence whitelist (E1 e1-r5..r13 + E2a re-verification): pin ->
# (gpio port index, pin, idle IDR level, assert level). Stock EX idles
# B11/C2/F6/G2 pulled up and C5/G14 floating; asserting drives the pin
# away from idle (low for the pulled-up four, high for C5/G14).
PINS = {
    'PB11': (1, 11, 1, 0), 'PC2': (2, 2, 1, 0), 'PF6': (5, 6, 1, 0),
    'PG2': (6, 2, 1, 0), 'PC5': (2, 5, 0, 1), 'PG14': (6, 14, 0, 1),
}
PUPDR = {1: 1 << (2 * 11), 2: 1 << (2 * 2), 5: 1 << (2 * 6), 6: 1 << (2 * 2)}

M4='''
.syntax unified
.cpu cortex-m4
.thumb
.section .text
.word 0x2004fff0
.word 0x08000041
.org 0x40
.thumb_func
start:
ldr r0, =0x4002040C
ldr r1, =0x00400000
str r1, [r0]
ldr r0, =0x4002080C
ldr r1, =0x00000010
str r1, [r0]
ldr r0, =0x4002140C
ldr r1, =0x00001000
str r1, [r0]
ldr r0, =0x4002180C
ldr r1, =0x00000010
str r1, [r0]
ldr r0, =0x20001000
movs r1, #0
loop:
adds r1, #1
str r1, [r0]
b loop
.ltorg
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--clang',default=os.environ.get('CLANG','clang'))
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report=dict(original_firmware_loaded=False,qemu_sha256=hashlib.sha256(args.qemu.read_bytes()).hexdigest(),checks=[])
    proc=qmp=None
    def check(name,passed):
        report['checks'].append(dict(name=name,passed=bool(passed)))
        if not passed:raise AssertionError(name)
    def compile(name,source,target,flags=()):
        text=out/(name+'.S');text.write_text(source);obj=out/(name+'.o');binary=out/(name+'.bin')
        subprocess.run([args.clang,'--target='+target,'-c',str(text),'-o',str(obj),*flags],check=True,capture_output=True)
        binary.write_bytes(elf_text(obj.read_bytes()));return binary
    a53=compile('a53',(FIXTURES/'a53-reset-heartbeat.S').read_text(),'aarch64-none-elf')
    mcu=compile('mcu',M4,'arm-none-eabi',('-mcpu=cortex-m4','-mthumb'))
    try:
        with tempfile.TemporaryDirectory(prefix='z8-card-detect-') as temp:
            def boot(machine,name):
                endpoint=Path(temp)/('qmp-'+name)
                command=[str(args.qemu.resolve()),'-M',machine,
                    '-cpu','cortex-a53','-smp','4,maxcpus=5','-kernel',str(a53),'-accel','tcg,thread=single',
                    '-display','none','-serial','none','-monitor','none','-nic','none','-S','-no-reboot',
                    '-qmp',f'unix:{endpoint},server=on,wait=off']
                log=(out/f'stderr-{name}.log').open('wb')
                child=subprocess.Popen(command,stdout=log,stderr=log)
                wait_for_sockets(child,endpoint)
                return child,QMP(endpoint)
            report['boots']=[]
            machine=f'nikon-z8-lab,mcu-image={mcu},bootstrap-fixtures=on,bus-window-fixture=on,serial-fixture=on,image-bank-model=on'
            proc,qmp=boot(machine,'native')
            def io():
                qmp.command('cont');time.sleep(.02);qmp.command('stop')
                return {g['port']:g for g in json.loads(qmp.command('qom-get',path='/machine',property='native-mcu-io-state'))['gpio']}
            deadline=time.monotonic()+5
            while True:
                gpio=io()
                if all(gpio[p]['pull']==v for p,v in PUPDR.items()) or time.monotonic()>deadline:break
            check('M4 fixture applied the stock-EX pull pattern',all(gpio[p]['pull']==v for p,v in PUPDR.items()))
            def pin_state(gpio,name):
                port,pin,_,_=PINS[name]
                g=gpio[port]
                return bool((g['input']>>pin)&1),bool((g['driven']>>pin)&1)
            check('default off: no candidate pin is driven',all(not pin_state(gpio,n)[1] for n in PINS))
            check('default off: inputs idle at the measured levels',
                  all(pin_state(gpio,n)[0]==idle for n,(_,_,idle,_) in PINS.items()))
            check('default pin is PB11',qmp.command('qom-get',path='/machine',property='mcu-card-detect-pin')=='PB11')
            check('default detect level is off',qmp.command('qom-get',path='/machine',property='mcu-card-detect') is False)
            qmp.command('qom-set',path='/machine',property='mcu-card-detect',value=True)
            gpio=io();level,driven=pin_state(gpio,'PB11')
            check('detect on without an explicit pin drives the default PB11',driven and level==PINS['PB11'][3])
            qmp.command('qom-set',path='/machine',property='mcu-card-detect-pin',value='PC2')
            gpio=io()
            check('switching from the default releases PB11 and asserts PC2',
                  pin_state(gpio,'PB11')[0]==PINS['PB11'][2] and pin_state(gpio,'PC2')==(PINS['PC2'][3],True))
            qmp.command('qom-set',path='/machine',property='mcu-card-detect',value=False)
            gpio=io();level,driven=pin_state(gpio,'PC2')
            check('detect off after the switch returns PC2 to idle',driven and level==PINS['PC2'][2])
            for name in ('PB11','PC2','PF6','PG2','PC5','PG14'):
                qmp.command('qom-set',path='/machine',property='mcu-card-detect-pin',value=name)
                qmp.command('qom-set',path='/machine',property='mcu-card-detect',value=True)
                gpio=io();level,driven=pin_state(gpio,name)
                check(f'{name} assert drives the measured assert level',driven and level==PINS[name][3])
                qmp.command('qom-set',path='/machine',property='mcu-card-detect',value=False)
                gpio=io();level,driven=pin_state(gpio,name)
                check(f'{name} release returns to the idle level',driven and level==PINS[name][2])
            qmp.command('qom-set',path='/machine',property='mcu-card-detect-pin',value='PC5')
            qmp.command('qom-set',path='/machine',property='mcu-card-detect',value=True)
            gpio=io()
            check('switching pins releases the previous candidate',
                  pin_state(gpio,'PG14')[0]==PINS['PG14'][2] and pin_state(gpio,'PC5')==(True,True))
            qmp.command('qom-set',path='/machine',property='mcu-card-detect-pin',value='pc2')
            check('lowercase pin spelling canonicalizes',qmp.command('qom-get',path='/machine',property='mcu-card-detect-pin')=='PC2')
            before=io()
            for value in ('G7','A0','B16','B11=0','','PC5=1','PB9'):
                rejected=False
                try:qmp.command('qom-set',path='/machine',property='mcu-card-detect-pin',value=value)
                except RuntimeError:rejected=True
                check('non-whitelisted pin rejected: '+repr(value),rejected)
            check('rejections left the pin state unchanged',io()==before)
            stop_child(proc,qmp);qmp=None;check('native boot reaped',proc.poll() is not None)
            machine='nikon-z8-lab,bootstrap-fixtures=on,bus-window-fixture=on,serial-fixture=on,image-bank-model=on'
            proc,qmp=boot(machine,'bare');report['boots'].append(machine)
            for prop,value in (('mcu-card-detect',True),('mcu-card-detect-pin','PB11')):
                rejected=False
                try:qmp.command('qom-set',path='/machine',property=prop,value=value)
                except RuntimeError as error:rejected='native MCU' in str(error)
                check(f'{prop} without native MCU is rejected',rejected)
            rejected=False
            try:qmp.command('qom-set',path='/machine',property='mcu-card-detect-pin',value='G7')
            except RuntimeError:rejected=True
            check('whitelist still enforced without native MCU',rejected)
            stop_child(proc,qmp);qmp=None;check('bare boot reaped',proc.poll() is not None)
    except Exception as error:
        report['error']=repr(error);raise
    finally:
        stop_child(proc,qmp);(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Passed',len(report['checks']),'mcu-card-detect checks; synthetic programs only')


if __name__=='__main__':main()
