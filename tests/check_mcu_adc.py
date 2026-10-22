#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise external ADC samples through actual synthetic M4 conversions."""
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
ldr r7, =0x20001000
ldr r0, [r7, #0x84]
adds r0, #1
str r0, [r7, #0x84]
again:
ldr r4, =0x40012000
mov r6, r7
movs r5, #3
next_adc:
movs r0, #1
str r0, [r4, #0x34]
ldr r0, =0x40000001
str r0, [r4, #8]
ldr r0, [r4, #0x4c]
str r0, [r6]
ldr r0, =0x00390820
str r0, [r4, #0x38]
ldr r0, =0x00400001
str r0, [r4, #8]
ldr r0, [r4, #0x3c]
str r0, [r6, #4]
ldr r0, [r4, #0x40]
str r0, [r6, #8]
ldr r0, [r4, #0x44]
str r0, [r6, #12]
ldr r0, [r4, #0x48]
str r0, [r6, #16]
ldr r0, [r4]
str r0, [r6, #20]
add.w r4, r4, #0x100
adds r6, #24
subs r5, #1
bne next_adc
ldr r0, [r7, #0x80]
adds r0, #1
str r0, [r7, #0x80]
ldr r0, [r7, #0x84]
cmp r0, #1
bne again
ldr r0, [r7, #64]
ldr r1, =4094
cmp r0, r1
bne again
ldr r0, =0xe000ed0c
ldr r1, =0x05fa0004
str r1, [r0]
b .
.ltorg
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--clang',default='clang')
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
        with tempfile.TemporaryDirectory(prefix='z8-adc-') as temp:
            endpoint=Path(temp)/'qmp'
            machine=f'nikon-z8-lab,mcu-image={mcu},mcu-adc-inputs=1.1=111:2.1=222:3.1=333:1.0=0:3.18=4095,bootstrap-fixtures=on,bus-window-fixture=on,serial-fixture=on,image-bank-model=on,statistics-raw='
            command=[str(args.qemu.resolve()),'-M',machine,
                '-cpu','cortex-a53','-smp','4,maxcpus=5','-kernel',str(a53),'-accel','tcg,thread=single',
                '-display','none','-serial','none','-monitor','none','-nic','none','-S','-no-reboot',
                '-qmp',f'unix:{endpoint},server=on,wait=off']
            with (out/'stderr.log').open('wb') as log:proc=subprocess.Popen(command,stdout=log,stderr=log)
            wait_for_sockets(proc,endpoint);qmp=QMP(endpoint)
            def state():return json.loads(qmp.command('qom-get',path='/machine',property='native-mcu-adc-state'))
            def set_inputs(value):return qmp.command('qom-set',path='/machine',property='mcu-adc-inputs',value=value)
            check('independent RAW path setter preserves ADC profile',qmp.command('qom-get',path='/machine',property='statistics-raw')=='')
            cold=state();check('cold input values and unchanged defaults',len(cold['adcs'])==3 and all(len(x['inputs'])==19 for x in cold['adcs']) and
                [x['inputs'][1] for x in cold['adcs']]==[111,222,333] and cold['adcs'][0]['inputs'][0]==0 and cold['adcs'][2]['inputs'][18]==4095 and cold['adcs'][1]['inputs'][18]==2048)
            check('sample setup creates no completion',all(x['status']==0 and x['data']==0 for x in cold['adcs']))
            def advance(previous,boots=1):
                qmp.command('cont');deadline=time.monotonic()+5
                while True:
                    time.sleep(.02);qmp.command('stop')
                    qmp.command('memsave',val=0x20001000,size=0x88,filename=str(out/'result.bin'),**{'cpu-index':4})
                    words=struct.unpack('<34I',(out/'result.bin').read_bytes())
                    if words[32]>previous and words[33]==boots:return words
                    if time.monotonic()>deadline:raise TimeoutError('M4 ADC program did not advance')
                    qmp.command('cont')
            words=advance(0)
            check('regular conversion uses three independent ADC inputs',[words[i*6] for i in range(3)]==[111,222,333])
            check('injected channels retain numeric order',list(words[1:5])==[0,111,2048,2048] and list(words[13:17])==[2048,333,2048,4095])
            before=state();check('read-only snapshot preserves completion state',state()==before)
            set_inputs('1.1=1234:2.0=45:3.18=0');updated=state()
            check('external changes do not run conversion or alter status',all({k:v for k,v in a.items() if k!='inputs'}=={k:v for k,v in b.items() if k!='inputs'} for a,b in zip(before['adcs'],updated['adcs'])))
            for value in ('1.0=1:3.19=0','1.0=1:0.0=0','1.0=1:2.0=4096','1.0=1:1.0=2','1.0=-1','1.0=0:', '1.0=0x10', '1.0= 1'):
                rejected=False
                try:set_inputs(value)
                except RuntimeError:rejected=True
                check('invalid batch remains atomic '+value,rejected and state()==updated)
            words=advance(words[32]);check('next conversions consume updated external samples',words[0]==1234 and words[7]==45 and words[16]==0)
            set_inputs('3.18=4094');words=advance(words[32],boots=2)
            check('external samples survive controller reset',words[0]==1234 and words[7]==45 and words[16]==4094 and state()['adcs'][2]['inputs'][18]==4094)
            qmp.command('pmemsave',val=0xa00010000,size=16,filename=str(out/'a53.bin'))
            heartbeat=struct.unpack('<2Q',(out/'a53.bin').read_bytes())
            check('A53 progresses independently of MCU reset',heartbeat[0]==0x4135334845415254 and heartbeat[1]>0)
            final=state();report['final_adc_state']=final
            stop_child(proc,qmp);qmp=None
            check('owned guest reaped',proc.poll() is not None)
    except Exception as error:
        report['error']=repr(error);raise
    finally:
        stop_child(proc,qmp);(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Passed',len(report['checks']),'actual MCU ADC checks; synthetic programs only')


if __name__=='__main__':main()
