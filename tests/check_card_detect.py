#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Check the external CFexpress detect input without executing Nikon code.

The NVMe endpoint and its file remain attached. This is a detect-line test,
not a storage hot-unplug or original-firmware mount/recovery qualification.
"""
import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import tempfile
from qemu_control import QMP, stop_child, wait_for_sockets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    bios = out/'synthetic-a53.bin'
    bios.write_bytes(bytes.fromhex('00000014'))
    card = out/'synthetic-card.raw'
    with card.open('xb') as target:
        target.truncate(16*1024*1024)
    report = dict(original_firmware_loaded=False,
                  qemu_sha256=hashlib.sha256(args.qemu.read_bytes()).hexdigest(),
                  checks=[])

    def check(name, passed):
        report['checks'].append(dict(name=name, passed=bool(passed)))
        if not passed:
            raise AssertionError(name)

    try:
        for initial in (True, False, None):
            proc = qmp = stream = sock = None
            try:
                with tempfile.TemporaryDirectory(prefix='z8-card-detect-') as temp:
                    endpoint, qtest = Path(temp)/'qmp', Path(temp)/'qtest'
                    properties = 'bootstrap-fixtures=on,bus-window-fixture=on,pcie-empty-fixture=on'
                    if initial is not None:
                        properties += ',pcie-link-diagnostic-mask=4,pcie-dbi-model=on'
                        if not initial:
                            properties += ',cfexpress-card-present=off'
                    command = [str(args.qemu.resolve()), '-M', 'nikon-z8-lab,'+properties,
                               '-cpu', 'cortex-a53', '-smp', '4', '-m', '512M',
                               '-kernel', str(bios), '-accel', 'qtest', '-S',
                               '-display', 'none', '-serial', 'none', '-monitor', 'none', '-nic', 'none',
                               '-qmp', f'unix:{endpoint},server=on,wait=off',
                               '-qtest', f'unix:{qtest},server=on,wait=off']
                    if initial is not None:
                        command += ['-drive', f'file={card},if=none,id=card,format=raw,file.locking=on',
                                    '-device', 'nvme,id=z8card,drive=card,serial=Z8-SYNTHETIC,bus=dw-pcie,addr=0']
                    with (out/f'qemu-{initial}.log').open('xb') as log:
                        proc = subprocess.Popen(command, stdout=log, stderr=log)
                    wait_for_sockets(proc, endpoint, qtest)
                    qmp = QMP(endpoint)
                    sock = socket.socket(socket.AF_UNIX)
                    sock.settimeout(3)
                    sock.connect(str(qtest))
                    stream = sock.makefile('rwb', buffering=0)

                    def read(address):
                        stream.write(f'readl {address:#x}\n'.encode())
                        while True:
                            reply = stream.readline().decode().strip()
                            if reply.startswith('IRQ '):
                                continue
                            if not reply.startswith('OK '):
                                raise RuntimeError(reply)
                            return int(reply.split()[1], 0)

                    def get(name):
                        return qmp.command('qom-get', path='/machine', property=name)

                    def present(value):
                        return qmp.command('qom-set', path='/machine',
                                           property='cfexpress-card-present', value=value)

                    if initial is None:
                        rejected = False
                        try:
                            present(False)
                        except RuntimeError:
                            rejected = True
                        check('absent adapter rejects runtime detect mutation',
                              rejected and get('cfexpress-card-present') is True and read(0x17a00044) == 0)
                        continue

                    prefix = 'present boot' if initial else 'absent boot'
                    check(prefix+' readback and port2 input',
                          get('cfexpress-card-present') is initial and read(0x17a00044) == (2 if initial else 0))
                    block, pci, adapter = qmp.command('query-block'), qmp.command('query-pci'), get('pcie-dbi-state')
                    report[prefix] = dict(block=block, pci=pci)
                    check(prefix+' has retained NVMe endpoint',
                          qmp.command('qom-get', path='/machine/peripheral/z8card', property='realized') is True and
                          len(block) == 1 and block[0]['inserted']['image']['filename'] == str(card))
                    for value in (False, False, True, True):
                        present(value)
                        check(prefix+' detect '+str(value),
                              get('cfexpress-card-present') is value and read(0x17a00044) == (2 if value else 0))
                        check(prefix+' neighbors and ownership '+str(value),
                              all(read(address) == 0 for address in (0x17a00034, 0x17a0003c, 0x17a0004c)) and
                              get('pcie-dbi-state') == adapter and qmp.command('query-block') == block and
                              qmp.command('query-pci') == pci)
                    check(prefix+' observation is read-only', get('cfexpress-card-present') is True and
                          get('pcie-dbi-state') == adapter and not qmp.command('query-status')['running'])
            finally:
                if stream:
                    stream.close()
                if sock:
                    sock.close()
                stop_child(proc, qmp)
        check('detect creates no storage writes', not any(card.read_bytes()))
    finally:
        (out/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    print(f"PASS {len(report['checks'])} external card-detect checks")


if __name__ == '__main__':
    main()
