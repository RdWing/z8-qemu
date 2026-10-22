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
ldr x2, [x0]
ret
.ltorg
'''
A53_APP='''
.section .text
ldr x6, =0xa00010000
ldr x1, =0x1234567812345678
ldr x2, =0xabcdef0176543210
ldr x3, =0xffffffff80000001
ldr x4, =0x88776655fedcba98
1: mov x0, x6
str x1, [x6]
bl numeric_log
mov x0, #0
bl numeric_log
mov x0, #1
bl numeric_log
ldr x0, =0xfffffffffffffff0
bl numeric_log
add x1, x1, #1
b 1b
.org 0x80
numeric_log: ret
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
ldr r2, [r0]
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
    app_image=compile_program('a53-app',A53_APP,'aarch64-none-elf')
    mcu_image=compile_program('m4',M4,'arm-none-eabi',('-mcpu=cortex-m4','-mthumb'))
    cases=[
        ('a53','cpu=0,calls=0x40160040,lo=0xa00010000,hi=0xa00010008,pclo=0x40160040,pchi=0x40160048,per_site=2,limit=8'),
        ('m4','cpu=4,calls=0x8000080,lo=0x20000000,hi=0x20000004,pclo=0x8000080,pchi=0x8000084,per_site=2,limit=8'),
        ('global-limit','calls=0x40160040:0x8000080,per_site=100,limit=3'),
        ('cpu-filter','cpu=4,calls=0x40160040,limit=8'),
        ('overlap','cpu=0,lo=0xa00010004,hi=0xa00010005,pclo=0x40160040,pchi=0x40160044,per_site=1'),
        ('outside-range','cpu=0,lo=0xa0000fff8,hi=0xa00010000,pclo=0x40160040,pchi=0x40160044'),
        ('outside-code','cpu=0,lo=0xa00010000,hi=0xa00010008,pclo=0x40160044,pchi=0x40160048'),
        ('a53-read','cpu=0,access=read,lo=0xa00010000,hi=0xa00010008,pclo=0x40160040,pchi=0x40160048,per_site=2'),
        ('m4-read','cpu=4,access=read,lo=0x20000000,hi=0x20000004,pclo=0x8000080,pchi=0x8000084,per_site=2'),
        ('both','cpu=0,access=both,lo=0xa00010000,hi=0xa00010008,pclo=0x40160040,pchi=0x40160048,per_site=2'),
        ('read-overlap','cpu=0,access=read,lo=0xa00010004,hi=0xa00010005,pclo=0x40160044,pchi=0x40160048,per_site=1'),
        ('read-excludes-store','cpu=0,access=read,lo=0xa00010000,hi=0xa00010008,pclo=0x40160040,pchi=0x40160044'),
        ('app-log','cpu=0,app_log=0x40160080,per_site=4,limit=12'),
        ('app-coexist','cpu=0,app_log=0x40160080,calls=0x40160080,lo=0xa00010000,hi=0xa00010008,pclo=0x40160018,pchi=0x4016001c,per_site=4,limit=16'),
        ('app-unsupported','cpu=4,app_log=0x8000080,per_site=2,limit=8'),
        ('app-cpu-filter','cpu=4,app_log=0x40160080,limit=8'),
    ]
    try:
        for name,options in cases:
            proc=qmp=None;case=out/name;case.mkdir();trace=case/'trace.log'
            try:
                with tempfile.TemporaryDirectory(prefix='z8-trace-check-') as temp:
                    endpoint=Path(temp)/'qmp'
                    command=[str(a.qemu.resolve()),'-M',f'nikon-z8-lab,mcu-image={mcu_image},bootstrap-fixtures=on,bus-window-fixture=on,serial-fixture=on,image-bank-model=on',
                        '-cpu','cortex-a53','-smp','4,maxcpus=5','-kernel',str(app_image if name.startswith('app-') else main_image),'-accel','tcg,thread=single',
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
                    elif name in ('a53-read','m4-read','both','read-overlap'):
                        cpu=4 if name=='m4-read' else 0
                        initial=0x56 if cpu==4 else 0x1234
                        address=0x20000000 if cpu==4 else 0xa00010000
                        pc=0x8000082 if cpu==4 else 0x40160044
                        reads=[x for x in events if x['event']=='read']
                        stores=[x for x in events if x['event']=='store']
                        count=1 if name=='read-overlap' else 2
                        check(name+' selected direction declared',rows[0]['access']==('both' if name=='both' else 'read'))
                        check(name+' exact read bounds and values',len(reads)==count and [int(x['value'],0) for x in reads]==list(range(initial,initial+count)))
                        check(name+' guest load location and width',all(x['cpu']==cpu and int(x['pc'],0)==pc and int(x['address'],0)==address and x['size']==(4 if cpu==4 else 8) for x in reads))
                        check(name+' write filtering',len(stores)==(2 if name=='both' else 0) and len(events)==len(reads)+len(stores))
                        if name=='both':check(name+' independent access caps',[int(x['value'],0) for x in stores]==[initial,initial+1] and summary['suppressed']>0)
                    elif name in ('app-log','app-coexist'):
                        decoded=[x for x in events if x['event']=='app_log']
                        check(name+' explicit schema and per-site bounds',len(decoded)==4 and summary['suppressed']>0 and rows[0]['app_log'])
                        check(name+' exact A53 entry',all(x['cpu']==0 and x['pc']=='0x40160080' and x['abi_available'] for x in decoded))
                        check(name+' low32 selector and all three payload registers',all(x['selector']==0x12345678 and x['payload']==[0x76543210,0x80000001,0xfedcba98] for x in decoded))
                        check(name+' null unaligned and unmapped objects are addresses only',[x['object'] for x in decoded]==['0xa00010000','0x0','0x1','0xfffffffffffffff0'])
                        check(name+' module unavailable without memory reads',all(x['module_id'] is None and x['module_id_source']=='not_read' and x['link'] is not None for x in decoded))
                        if name=='app-coexist':
                            calls=[x for x in events if x['event']=='call'];stores=[x for x in events if x['event']=='store']
                            check(name+' generic call contract retained',len(calls)==4 and all(len(x['args'])==4 for x in calls) and int(calls[0]['args'][1],0)==0x1234567812345678)
                            check(name+' store contract retained',len(stores)==4 and int(stores[0]['value'],0)==0x1234567812345678 and all(x['size']==8 for x in stores))
                    elif name=='app-unsupported':
                        check(name+' MCU schema explicitly unsupported',len(events)==2 and all(x['event']=='app_log' and not x['abi_available'] and x['reason']=='unsupported_architecture' for x in events))
                        check(name+' MCU registers never reinterpreted',all(x['object'] is None and x['selector'] is None and x['payload']==[None]*3 and x['link'] is None for x in events))
                    else:check(name+' excludes other CPU',events==[])
                    report['cases'].append(dict(name=name,events=events,summary=summary))
            finally:stop_child(proc,qmp)
        # Invalid/duplicate configuration and existing outputs must fail before
        # emitting any record; no QMP or Nikon input is needed for these cases.
        for index,options in enumerate(('calls=0x40160041','calls=0x40160040,limit=0',
            'calls=0x40160040,unknown=1','calls=0x40160040,cpu=0,cpu=1','lo=1,hi=2',
            'calls=0x40160040:0x40160040','app_log=0','app_log=0x40160081','app_log=0x40160082',
            'app_log=0x40160080,app_log=0x40160080','app_log=not-a-number',
            'calls=0x40160040,access=read','lo=1,hi=2,pclo=1,pchi=2,access=invalid',
            'lo=1,hi=2,pclo=1,pchi=2,access=read,access=both')):
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
