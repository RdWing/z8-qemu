#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Actual-board finite TX consumption and rejection checks; no Nikon firmware."""
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
                     'duplicate', 'different-fifo'):
            proc = qmp = sock = stream = None
            try:
                with tempfile.TemporaryDirectory(prefix='z8-audio-tx-') as temp:
                    endpoint, qt = Path(temp)/'qmp', Path(temp)/'qtest'
                    props = 'bootstrap-fixtures=on,bus-window-fixture=on,serial-fixture=on'
                    if case != 'disabled':
                        props += ',serial5-tx-drain-model=on'
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
                    sock.settimeout(3)
                    sock.connect(str(qt))
                    stream = sock.makefile('rwb', buffering=0)

                    def qtcmd(value):
                        stream.write(value.encode()+b'\n')
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

                    # Explicit local-read mapping to a separate CPU RAM page.
                    for offset, value in ((0, 0x40000000), (8, 0xfffff0000),
                                          (16, 0xe00000000)):
                        qtcmd(f'writeq {0x14154040+offset:#x} {value:#x}')
                    source = bytes((i*37+11) & 255 for i in range(128))
                    qtcmd(f'write 0xa00001000 0x80 0x{source.hex()}')
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
                    if case == 'different-fifo':
                        fields[24] += 4
                    for offset, value in fields.items():
                        write(base+offset, value)
                    request = (0x9a000000 if case == 'wrong-request' else 0x9b000000) | 31
                    write(base, request)
                    if case == 'duplicate':
                        for offset, value in fields.items():
                            write(base+0x20+offset, value)
                        write(base+0x20, request)
                    write(0x0e200108, 0x45002000)
                    report.setdefault('cases', {})[case] = {'armed': state()}
                    check(case+': no early completion', state()['jobs'] == 0 and
                          read(base) & 0x80000000)
                    qtcmd('clock_step 500000')
                    check(case+': deadline separates request from completion', state()['jobs'] == 0)
                    if case == 'cancel':
                        write(0x0e200108, 0x45000000)
                    qtcmd('clock_step 1500000')
                    result = state()
                    report['cases'][case]['after_deadline'] = result
                    if case == 'complete':
                        check('consumed exact mapped bytes before success', result['jobs'] == 1 and
                              result['bytes'] == 128 and result['last_source'] == 0xa00001000 and
                              result['sha256'] == hashlib.sha256(source).hexdigest())
                        check('original DMA status is completed', not read(base) & 0x80000000 and
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
                              result['bytes'] == 0 and read(base) & 0x80000000 and
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
