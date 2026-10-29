#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Actual-board stereo host output and WAV finalization; no Nikon firmware."""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import tempfile
from qemu_control import QMP, stop_child, wait_for_sockets


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--qemu', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--backend', choices=('wav','auto'), default='wav')
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    bios = out/'synthetic-a53.bin'
    bios.write_bytes(bytes.fromhex('00000014'))
    report = dict(original_firmware_loaded=False, checks=[],
                  qemu_sha256=hashlib.sha256(args.qemu.read_bytes()).hexdigest())

    def check(name, value):
        report['checks'].append(dict(name=name, passed=bool(value)))
        if not value:
            raise AssertionError(name)

    try:
        for case in ('paired-large',):
            proc = qmp = sock = stream = None
            try:
                with tempfile.TemporaryDirectory(prefix='z8-audio-tx-') as temp:
                    endpoint, qt = Path(temp)/'qmp', Path(temp)/'qtest'
                    props = 'bootstrap-fixtures=on,bus-window-fixture=on,serial-fixture=on'
                    props += ',serial5-tx-drain-model=on'
                    command = [str(args.qemu.resolve()), '-M', 'nikon-z8-lab,'+props,
                               '-cpu', 'cortex-a53', '-smp', '4', '-m', '512M',
                               '-kernel', str(bios), '-accel', 'qtest',
                               '-display', 'none', '-serial', 'none', '-monitor', 'none',
                               '-qmp', f'unix:{endpoint},server=on,wait=off',
                               '-qtest', f'unix:{qt},server=on,wait=off']
                    backend = 'auto' if args.backend == 'auto' else 'z8audio'
                    command[command.index('-M')+1]+=',serial5-audio-output='+backend
                    if args.backend == 'wav':
                        command+=['-audiodev',f'wav,id=z8audio,path={out}/host.wav,out.frequency=48000,out.channels=2,out.format=s16']
                    with (out/(case+'.log')).open('xb') as log:
                        proc = subprocess.Popen(command, stdout=log, stderr=log)
                    wait_for_sockets(proc, endpoint, qt)
                    qmp = QMP(endpoint)
                    sock = socket.socket(socket.AF_UNIX)
                    sock.settimeout(30)
                    sock.connect(str(qt))
                    stream = sock.makefile('rwb', buffering=0)

                    def qtcmd(value):
                        sock.sendall(value.encode()+b'\n')
                        while True:
                            row = stream.readline().decode().strip()
                            if row.startswith('IRQ '):
                                continue
                            if not row.startswith('OK'):
                                raise RuntimeError(row)
                            return row.split()[1:]

                    def write(a, v):
                        qtcmd(f'writel {a:#x} {v:#x}')

                    def read(a):
                        return int(qtcmd(f'readl {a:#x}')[0], 0)

                    def state():
                        return json.loads(qmp.command('qom-get', path='/machine',
                                                     property='serial5-tx-drain-state'))

                    transfer_bytes=192192
                    # Explicit local-read mapping to a separate CPU RAM page.
                    for offset, value in ((0, 0x40000000), (8, 0xfffe00000),
                                          (16, 0xe00000000)):
                        qtcmd(f'writeq {0x14154040+offset:#x} {value:#x}')
                    source = bytes.fromhex('00000010000000f0')*(transfer_bytes//8)
                    for o in range(0,len(source),4096):
                        b=source[o:o+4096];qtcmd(f'write {0xa00001000+o:#x} {len(b):#x} 0x{b.hex()}')
                    write(0x0e110000, 0x80000000)
                    base = 0x0e110100
                    fields = {4: 0x29f80000, 8: 0x404, 12: 0,
                              16: 0x40001000, 24: 0x0e200104}
                    fields[24] = 0x0e20013c
                    for offset, value in fields.items():
                        write(base+offset, value)
                    request = 0x9b000000 | (transfer_bytes//4-1)
                    write(base, request)
                    second=bytes.fromhex('000000f000000010')*(transfer_bytes//8)
                    for offset in range(0,len(second),4096):
                        block=second[offset:offset+4096]
                        qtcmd(f'write {0xa00100000+offset:#x} {len(block):#x} 0x{block.hex()}')
                    for offset,value in fields.items():
                        write(base+0x20+offset,0x40100000 if offset==16 else value)
                    write(base+0x20,0x9c000000|(transfer_bytes//4-1))
                    write(0x0e200108,0x4d002002)
                    armed_base=base
                    report.setdefault('cases', {})[case] = {'armed': state()}
                    check(case+': no early completion', state()['jobs'] == 0 and
                          read(armed_base) & 0x80000000)
                    qtcmd('clock_step 500000')
                    check(case+': deadline separates request from completion', state()['jobs'] == 0)
                    qtcmd('clock_step 499999')
                    check('large first block remains pending before prefill deadline',state()['jobs']==0)
                    qtcmd('clock_step 1')
                    check('large first prefill completes at 1000000ns',state()['jobs']==1 and state()['bytes']==192192)
                    qtcmd('clock_step 500499999')
                    check('large second block remains pending until its own deadline',state()['jobs']==1)
                    qtcmd('clock_step 1')
                    qtcmd('clock_step 1500000')
                    qtcmd('clock_step 1500000000')
                    result = state()
                    report['cases'][case]['after_deadline'] = result
                    check('host output accepts all actual samples without a fault',
                          result['host_output'] and not result['fault'] and
                          result['host_pcm_bytes']+result['host_queue_bytes']==transfer_bytes*2)
                    check('paired actual RAM blocks both consumed in phase order',
                          result['jobs']==2 and result['bytes']==transfer_bytes*2 and
                          result['sha256']==hashlib.sha256(source+second).hexdigest())
                    check('both actual DMA descriptors retired',
                          not read(base)&0x80000000 and not read(base+0x20)&0x80000000)
                    check(case+': no physical audio claim', not result['dac_output'] and
                          not result['physical_timing_verified'])
            finally:
                stop_child(proc, qmp)
                if args.backend == 'wav':
                    import wave
                    with wave.open(str(out/'host.wav'),'rb') as wav:
                        check('host backend emits stereo 48k PCM16',wav.getnchannels()==2 and wav.getframerate()==48000 and wav.getsampwidth()==2)
                        pcm=wav.readframes(wav.getnframes())
                    actual=b''.join(pcm[o:o+4] for o in range(0,len(pcm),4) if pcm[o:o+4]!=b'\0'*4)
                    expected=bytes.fromhex('ff0f01f0')*(transfer_bytes//8)+bytes.fromhex('01f0ff0f')*(transfer_bytes//8)
                    check('host WAV contains both real blocks in exact sample order',actual==expected)
                if stream:
                    stream.close()
                if sock:
                    sock.close()
    finally:
        (out/'result.json').write_text(json.dumps(report, indent=2)+'\n')
    print('Passed', len(report['checks']), 'audio TX checks')


if __name__ == '__main__':
    main()
