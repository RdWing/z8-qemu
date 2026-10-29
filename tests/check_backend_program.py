#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Actual-board bounded processing-program replacement; no Nikon firmware."""
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
        for case in ('enabled','disabled'):
            proc = qmp = sock = stream = None
            try:
                with tempfile.TemporaryDirectory(prefix='z8-program-') as temp:
                    endpoint, qt = Path(temp)/'qmp', Path(temp)/'qtest'
                    props = 'bootstrap-fixtures=on,bus-window-fixture=on,serial-fixture=on'
                    props += ',engine152c-config-model=on'
                    if case == 'enabled':
                        props += ',backend-program-epoch-model=on'
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
                                                     property='backend-program-epoch-state'))

                    check(case+': explicit gate',state()['enabled']==(case=='enabled'))
                    for epoch in range(8):
                        before=state()['retained_words']
                        for address,value in ((0x152c0404,1),(0x152c0004,1),
                                              (0x152c0000,1),(0x152c0004,0),
                                              (0x152c0000,0),(0x152c0404,0)):
                            write(address,value)
                        check(case+': reset retains previous opaque program',
                              state()['retained_words']==before)
                        for word in range(14):
                            write(0x15ac0050,0x10000000+epoch*16+word)
                        current=state()
                        check(case+': no execution or completion claim',
                              not current['program_execution_verified'] and current['latches']==0)
                        if case=='enabled':
                            check('replacement epoch stays bounded at 14 words',
                                  current['retained_words']==14 and current['cursor']==14 and
                                  current['uploaded_words']==14*(epoch+1) and
                                  current['reset_epochs']==epoch+1)
                        else:
                            check('default-off cumulative buffer remains strict',
                                  current['retained_words']==min(64,14*(epoch+1)) and
                                  current['reset_epochs']==0)
                    config=json.loads(qmp.command('qom-get',path='/machine',
                                                 property='engine152c-config-state'))
                    check(case+': retention produces no pixels or IRQ results',
                          config['jobs']==0 and config['pixel_bytes']==0 and
                          config['completion_events']==0)
                    if case=='enabled':
                        check('only newest complete program retained',
                              config['fifo']==[0x10000000+7*16+word for word in range(14)])
            finally:
                stop_child(proc, qmp)
                if stream:
                    stream.close()
                if sock:
                    sock.close()
    finally:
        (out/'result.json').write_text(json.dumps(report, indent=2)+'\n')
    print('Passed', len(report['checks']), 'backend program checks')


if __name__ == '__main__':
    main()
