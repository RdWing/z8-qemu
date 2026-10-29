#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Actual-board finite TX consumption and rejection checks; no Nikon firmware."""
import argparse
import base64
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
        for case in ('disabled', 'complete', 'cancel', 'global-off',
                     'wrong-request', 'wrong-width', 'unmapped', 'misaligned',
                     'duplicate', 'different-fifo', 'paired', 'paired-cancel', 'paired-duplicate', 'paired-unmapped', 'paired-second-only', 'paired-large'):
            proc = qmp = sock = stream = None
            try:
                with tempfile.TemporaryDirectory(prefix='z8-audio-tx-') as temp:
                    endpoint, qt = Path(temp)/'qmp', Path(temp)/'qtest'
                    props = 'bootstrap-fixtures=on,bus-window-fixture=on,serial-fixture=on'
                    if case != 'disabled':
                        props += ',serial5-tx-drain-model=on'
                    if case == 'paired-large':
                        props += ',serial5-playback-ram-aperture-fixture=on'
                    command = [str(args.qemu.resolve()), '-M', 'nikon-z8-lab,'+props,
                               '-cpu', 'cortex-a53', '-smp', '4', '-m', '512M',
                               '-kernel', str(bios), '-accel', 'qtest',
                               '-display', 'none', '-serial', 'none', '-monitor', 'none',
                               '-qmp', f'unix:{endpoint},server=on,wait=off',
                               '-qtest', f'unix:{qt},server=on,wait=off']
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

                    if case in ('complete', 'paired-large'):
                        check(case+': playback aperture is explicit', qmp.command(
                            'qom-get', path='/machine', property='serial5-playback-ram-aperture-fixture') == (case == 'paired-large'))
                        if case == 'paired-large':
                            offsets = [int(qtcmd(f'readq {0x14154260+entry*0x20+0x10:#x}')[0], 0)
                                       for entry in range(16)]
                            check('playback aperture retains recording and sound aliases', offsets ==
                                  [0x78000000 if entry in (12, 13) else 0x200000000 for entry in range(16)])
                        for prop, value in (('serial5-playback-ram-aperture-fixture', False),
                                            ('serial5-audio-output', 'none')):
                            try:
                                qmp.command('qom-set', path='/machine', property=prop, value=value)
                            except RuntimeError:
                                check(prop+': immutable after realization', True)
                            else:
                                check(prop+': immutable after realization', False)
                    transfer_bytes=192192 if case=='paired-large' else 128
                    # Explicit local-read mapping to a separate CPU RAM page.
                    for offset, value in ((0, 0x40000000), (8, 0xfffe00000),
                                          (16, 0xe00000000)):
                        qtcmd(f'writeq {0x14154040+offset:#x} {value:#x}')
                    source = bytes((i*37+11) & 255 for i in range(transfer_bytes))
                    for o in range(0,len(source),4096):
                        b=source[o:o+4096];qtcmd(f'write {0xa00001000+o:#x} {len(b):#x} 0x{b.hex()}')
                    write(0x0e110000, 0 if case == 'global-off' else 0x80000000)
                    base = 0x0e110100
                    fields = {4: 0x29f80000, 8: 0x404, 12: 0,
                              16: 0x40001000, 24: 0x0e200104}
                    if case == 'wrong-width':
                        fields[4] = 0x25f80000
                    if case == 'unmapped':
                        fields[16] = 0x1000
                    if case == 'misaligned':
                        fields[16] += 1
                    if case.startswith('paired'):fields[24]=0x0e20013c
                    if case == 'different-fifo':
                        fields[24] += 4
                    for offset, value in fields.items():
                        write(base+offset, value)
                    request = (0x9a000000 if case == 'wrong-request' else 0x9b000000) | (transfer_bytes//4-1)
                    write(base, request)
                    if case == 'duplicate':
                        for offset, value in fields.items():
                            write(base+0x20+offset, value)
                        write(base+0x20, request)
                    if case.startswith('paired'):
                        second=bytes(x^0xff for x in source)
                        for o in range(0,len(second),4096):
                            b=second[o:o+4096];qtcmd(f'write {0xa00100000+o:#x} {len(b):#x} 0x{b.hex()}')
                        for offset,value in fields.items():write(base+0x20+offset,0x40100000 if offset==16 else value)
                        write(base+0x20,(0x9b000000 if case=='paired-duplicate' else 0x9c000000)|(transfer_bytes//4-1))
                        if case=='paired-unmapped':write(base+0x20+16,0x1000)
                        if case=='paired-second-only':write(base,0x1b00001f)
                    write(0x0e200108,0x4d002002 if case.startswith('paired') else 0x45002000)
                    armed_base=base+0x20 if case=='paired-second-only' else base
                    report.setdefault('cases', {})[case] = {'armed': state()}
                    check(case+': no early completion', state()['jobs'] == 0 and
                          read(armed_base) & 0x80000000)
                    qtcmd('clock_step 500000')
                    check(case+': deadline separates request from completion', state()['jobs'] == 0)
                    if case == 'cancel':
                        write(0x0e200108, 0x45000000)
                    if case=='paired-large':
                        qtcmd('clock_step 499999')
                        check('large first block remains pending before prefill deadline',state()['jobs']==0)
                        qtcmd('clock_step 1')
                        check('large first prefill completes at 1000000ns',state()['jobs']==1 and state()['bytes']==192192)
                        qtcmd('clock_step 500499999')
                        check('large second block remains pending until its own deadline',state()['jobs']==1)
                        qtcmd('clock_step 1')
                    if case=='paired-cancel':
                        qtcmd('clock_step 500000');write(0x0e200108,0x4d000002)
                    qtcmd('clock_step 1500000')
                    result = state()
                    report['cases'][case]['after_deadline'] = result
                    if case=='paired-cancel':
                        check('paired cancellation retains first actual block only',result['jobs']==1 and result['bytes']==128 and result['sha256']==hashlib.sha256(source).hexdigest() and bool(read(base+0x20)&0x80000000))
                    elif case in ('paired','paired-large'):
                        check('paired actual RAM blocks both consumed in phase order',result['jobs']==2 and result['bytes']==transfer_bytes*2 and result['sha256']==hashlib.sha256(source+second).hexdigest())
                        capture = base64.b64decode(qmp.command('qom-get', path='/machine', property='serial5-tx-pcm-capture'))
                        check('explicit capture contains actual source bytes only', capture == source+second)
                        check('both actual DMA descriptors retired',not read(base)&0x80000000 and not read(base+0x20)&0x80000000)
                    elif case == 'complete':
                        check('consumed exact mapped bytes before success', result['jobs'] == 1 and
                              result['bytes'] == 128 and result['last_source'] == 0xa00001000 and
                              result['sha256'] == hashlib.sha256(source).hexdigest())
                        check('original DMA status is completed', not read(armed_base) & 0x80000000 and
                              (read(base+4) >> 16) & 7 == 5)
                        check('source RAM is preserved', qtcmd('read 0xa00001000 0x80')[0] == '0x'+source.hex())
                        check('retired FIFO is empty', read(0x0e20011c) == 0 and state()['empty_reads'] == 1)
                        qtcmd('clock_step 10000000')
                        check('retired descriptor cannot complete twice', state()['jobs'] == 1)
                        try:
                            qmp.command('qom-set', path='/machine', property='serial5-tx-drain-model', value=False)
                        except RuntimeError:
                            check('model selection immutable after transfer', True)
                        else:
                            check('model selection immutable after transfer', False)
                    else:
                        check(case+': no bytes or success manufactured', result['jobs'] == 0 and
                              result['bytes'] == 0 and read(armed_base) & 0x80000000 and
                              not read(base+4) & 0x70000)
                    check(case+': no physical audio claim', not result['dac_output'] and
                          not result['physical_timing_verified'])
            finally:
                stop_child(proc, qmp)
                if stream:
                    stream.close()
                if sock:
                    sock.close()
    finally:
        (out/'result.json').write_text(json.dumps(report, indent=2)+'\n')
    print('Passed', len(report['checks']), 'audio TX checks')


if __name__ == '__main__':
    main()
