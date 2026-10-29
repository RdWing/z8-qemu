# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Check real general-DMA copies and identity/overlap boundaries on the board.

Uses synthetic RAM only. No camera firmware or saved media is loaded.
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
    options = parser.parse_args()
    output = options.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    bios = output / 'synthetic.bin'
    bios.write_bytes(bytes.fromhex('00000014'))
    checks = []

    def check(name, passed):
        checks.append({'name': name, 'passed': bool(passed)})
        if not passed:
            raise AssertionError(name)

    proc = qmp = sock = stream = None
    try:
        with tempfile.TemporaryDirectory(prefix='z8-gdma-') as temporary:
            endpoint, qt = Path(temporary) / 'qmp', Path(temporary) / 'qtest'
            args = [str(options.qemu.resolve()), '-M',
                    'nikon-z8-lab,bootstrap-fixtures=on', '-cpu', 'cortex-a53',
                    '-smp', '4', '-m', '512M', '-kernel', str(bios),
                    '-accel', 'qtest', '-display', 'none', '-serial', 'none',
                    '-monitor', 'none', '-qmp', f'unix:{endpoint},server=on,wait=off',
                    '-qtest', f'unix:{qt},server=on,wait=off']
            with (output / 'qemu.log').open('wb') as log:
                proc = subprocess.Popen(args, stdout=log, stderr=log)
            wait_for_sockets(proc, endpoint, qt)
            qmp = QMP(endpoint)
            sock = socket.socket(socket.AF_UNIX)
            sock.connect(str(qt))
            stream = sock.makefile('rwb', buffering=0)

            def command(value):
                stream.write((value + '\n').encode())
                while True:
                    reply = stream.readline().decode().strip()
                    if reply.startswith('IRQ '):
                        continue
                    if not reply.startswith('OK'):
                        raise RuntimeError(reply)
                    return reply.split()[1:]

            def write(address, value):
                command(f'writel {address:#x} {value:#x}')

            def read(address, count):
                return bytes.fromhex(command(f'read {address:#x} {count:#x}')[0][2:])

            def data(address, value):
                command(f'write {address:#x} {len(value):#x} 0x{value.hex()}')

            base, source, destination = 0x0c850010, 0x40100000, 0x40140000
            pattern = bytes((i * 73 + 9) & 255 for i in range(192192))
            data(source - 16, b'A' * 16 + pattern + b'B' * 16)
            data(destination - 16, b'C' * 16 + bytes(len(pattern)) + b'D' * 16)

            def transfer(src, dst, count, source_mode=0x30f00):
                write(base + 0x20, 0)
                values = [count - 1, src, dst, source_mode, 0x30f00, 0]
                for index, value in enumerate(values):
                    write(base + index * 4, value)
                write(base + 0x18, 0x11109003)
                return int(command(f'readl {base + 0x20:#x}')[0], 0)

            check('identity transfer completes', transfer(source, source, len(pattern)) == 8)
            check('identity transfer retains every byte and both canaries',
                  read(source - 16, len(pattern) + 32) == b'A' * 16 + pattern + b'B' * 16)
            write(base + 0x20, 0)
            check('completion acknowledgement retires status',
                  int(command(f'readl {base + 0x20:#x}')[0], 0) == 0)
            check('disjoint transfer completes', transfer(source, destination, len(pattern)) == 8)
            check('disjoint copy writes exact bytes without crossing its destination',
                  read(destination - 16, len(pattern) + 32) == b'C' * 16 + pattern + b'D' * 16)
            for label, src, dst, count in [
                ('forward partial overlap', source, source + 4, len(pattern) - 4),
                ('backward partial overlap', source + 4, source, len(pattern) - 4),
                ('unmapped source', 0x30000000, destination, len(pattern)),
                ('unmapped destination', source, 0x30000000, len(pattern)),
                ('over-budget identity', source, source, 65 * 1024 * 1024),
            ]:
                check(label + ' produces no completion', transfer(src, dst, count) == 0)
                check(label + ' preserves source and destination',
                      read(source - 16, len(pattern) + 32) == b'A' * 16 + pattern + b'B' * 16 and
                      read(destination - 16, len(pattern) + 32) == b'C' * 16 + pattern + b'D' * 16)
            check('identity cannot bypass source-mode validation',
                  transfer(source, source, len(pattern), 0x30f04) == 0)
            check('invalid identity leaves its bytes unchanged', read(source, len(pattern)) == pattern)
    finally:
        if qmp:
            qmp.close()
        if stream:
            stream.close()
        if sock:
            sock.close()
        if proc:
            stop_child(proc, None)
        report = {'original_firmware_loaded': False,
                  'qemu_sha256': hashlib.sha256(options.qemu.read_bytes()).hexdigest(),
                  'checks': checks}
        (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(f'{len(checks)} general-DMA checks passed')


if __name__ == '__main__':
    main()
