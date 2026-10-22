#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise the actual QEMU 11 plugin on synthetic A53/M4 programs only."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import time
from check_mcu_reset import elf_text
from qemu_control import QMP, stop_child, wait_for_sockets

A53='''
.section .text
ldr x0, =0xa00010000
mov x1, #0x1234
1: bl sample
add x1, x1, #1
b 1b
.org 0x40
sample: str x1, [x0]
ret
.ltorg
'''
M4='''
.syntax unified
.cpu cortex-m4
.thumb
.section .text
.word 0x2004fff0
.word 0x08000041
.org 0x40
ldr r0, =0x20000000
movs r1, #0x56
1: bl sample
adds r1, #1
b 1b
.org 0x80
.thumb_func
sample: str r1, [r0]
bx lr
.ltorg
'''


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--qemu',type=Path,required=True)
    p.add_argument('--plugin',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--clang',default='clang')
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report=dict(original_firmware_loaded=False,qemu_sha256=hashlib.sha256(a.qemu.read_bytes()).hexdigest(),
        plugin_sha256=hashlib.sha256(a.plugin.read_bytes()).hexdigest(),checks=[],cases=[])
    def check(name,passed):
        report['checks'].append(dict(name=name,passed=bool(passed)))
        if not passed:raise AssertionError(name)
    def compile_program(name,code,target,flags=()):
        source=out/(name+'.S');source.write_text(code);obj=out/(name+'.o');image=out/(name+'.bin')
        subprocess.run([a.clang,'--target='+target,'-c',str(source),'-o',str(obj),*flags],check=True,capture_output=True)
        image.write_bytes(elf_text(obj.read_bytes()));return image
    main_image=compile_program('a53',A53,'aarch64-none-elf')
    mcu_image=compile_program('m4',M4,'arm-none-eabi',('-mcpu=cortex-m4','-mthumb'))
    cases=[
        ('a53','cpu=0,calls=0x40160040,lo=0xa00010000,hi=0xa00010008,pclo=0x40160040,pchi=0x40160048,per_site=2,limit=8'),
        ('m4','cpu=4,calls=0x8000080,lo=0x20000000,hi=0x20000004,pclo=0x8000080,pchi=0x8000084,per_site=2,limit=8'),
        ('global-limit','calls=0x40160040:0x8000080,per_site=100,limit=3'),
        ('cpu-filter','cpu=4,calls=0x40160040,limit=8'),
        ('overlap','cpu=0,lo=0xa00010004,hi=0xa00010005,pclo=0x40160040,pchi=0x40160044,per_site=1'),
        ('outside-range','cpu=0,lo=0xa0000fff8,hi=0xa00010000,pclo=0x40160040,pchi=0x40160044'),
        ('outside-code','cpu=0,lo=0xa00010000,hi=0xa00010008,pclo=0x40160044,pchi=0x40160048'),
    ]
    try:
        for name,options in cases:
            proc=qmp=None;case=out/name;case.mkdir();trace=case/'trace.log'
            try:
                with tempfile.TemporaryDirectory(prefix='z8-trace-check-') as temp:
                    endpoint=Path(temp)/'qmp'
                    command=[str(a.qemu.resolve()),'-M',f'nikon-z8-lab,mcu-image={mcu_image},bootstrap-fixtures=on,bus-window-fixture=on,serial-fixture=on,image-bank-model=on',
                        '-cpu','cortex-a53','-smp','4,maxcpus=5','-kernel',str(main_image),'-accel','tcg,thread=single',
                        '-display','none','-serial','none','-monitor','none','-nic','none','-S','-no-reboot',
                        '-qmp',f'unix:{endpoint},server=on,wait=off','-plugin',f'{a.plugin.resolve()},out={trace},{options}']
                    with (case/'stderr.log').open('wb') as log:proc=subprocess.Popen(command,stdout=log,stderr=log)
                    wait_for_sockets(proc,endpoint);qmp=QMP(endpoint);qmp.command('cont')
                    deadline=time.monotonic()+5
                    while True:
                        time.sleep(.02)
                        qmp.command('stop');qmp.command('pmemsave',val=0xa00010000,size=8,filename=str(case/'main.bin'))
                        qmp.command('memsave',val=0x20000000,size=4,filename=str(case/'mcu.bin'),**{'cpu-index':4})
                        first=struct.unpack('<Q',(case/'main.bin').read_bytes())[0]
                        mcu=struct.unpack('<I',(case/'mcu.bin').read_bytes())[0]
                        if first>0x1235 and mcu>0x57:break
                        if time.monotonic()>deadline:raise TimeoutError('Synthetic CPUs did not both advance')
                        qmp.command('cont')
                    check(name+' independent guest programs advance',first>0x1235 and mcu>0x57)
                    stop_child(proc,qmp);qmp=None
                    rows=[json.loads(line) for line in trace.read_text().splitlines()]
                    events=rows[1:-1];summary=rows[-1]
                    check(name+' clean summary and reaping',summary['event']=='summary' and proc.poll() is not None)
                    check(name+' host clock declared',rows[0]['clock']=='host_monotonic_us')
                    check(name+' bounded and accounted',summary['emitted']==len(events) and len(events)<=rows[0]['limit'])
                    if name in ('a53','m4'):
                        cpu=0 if name=='a53' else 4;expected_pc=0x40160040 if cpu==0 else 0x8000080
                        address=0xa00010000 if cpu==0 else 0x20000000;initial=0x1234 if cpu==0 else 0x56
                        call_rows=[x for x in events if x['event']=='call'];stores=[x for x in events if x['event']=='store']
                        check(name+' exact per-site caps',len(call_rows)==len(stores)==2 and summary['suppressed']>0)
                        check(name+' exact CPU and instruction',all(x['cpu']==cpu and int(x['pc'],0)==expected_pc for x in events))
                        check(name+' actual register values',int(call_rows[0]['args'][0],0)==address and int(call_rows[0]['args'][1],0)==initial and call_rows[0]['link'] is not None)
                        check(name+' actual memory values',[int(x['value'],0) for x in stores]==[initial,initial+1] and all(int(x['address'],0)==address and x['size']==(8 if cpu==0 else 4) for x in stores))
                    elif name=='global-limit':check(name+' enforced',len(events)==3 and summary['suppressed']>0)
                    elif name=='overlap':check(name+' includes crossing store',len(events)==1 and events[0]['address']=='0xa00010000' and events[0]['size']==8)
                    else:check(name+' excludes other CPU',events==[])
                    report['cases'].append(dict(name=name,events=events,summary=summary))
            finally:stop_child(proc,qmp)
        # Invalid/duplicate configuration and existing outputs must fail before
        # emitting any record; no QMP or Nikon input is needed for these cases.
        for index,options in enumerate(('calls=0x40160041','calls=0x40160040,limit=0',
            'calls=0x40160040,unknown=1','calls=0x40160040,cpu=0,cpu=1','lo=1,hi=2',
            'calls=0x40160040:0x40160040')):
            trace=out/f'invalid-{index}.log'
            command=[str(a.qemu.resolve()),'-M','virt','-display','none','-serial','none','-monitor','none','-S',
                     '-plugin',f'{a.plugin.resolve()},out={trace},{options}']
            result=subprocess.run(command,capture_output=True,timeout=5)
            check('invalid plugin options '+str(index),result.returncode!=0 and not trace.exists())
        trace=out/'existing.log';trace.write_bytes(b'preserved')
        result=subprocess.run([str(a.qemu.resolve()),'-M','virt','-display','none','-S','-plugin',
            f'{a.plugin.resolve()},out={trace},calls=0x40160040'],capture_output=True,timeout=5)
        check('existing output never overwritten',result.returncode!=0 and trace.read_bytes()==b'preserved')
    finally:(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(str(len(report['checks']))+' actual-plugin checks passed')


if __name__=='__main__':main()
