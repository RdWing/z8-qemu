#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Execute synthetic A53/M4 programs to check the MCU reset domain.

Requires clang with AArch64/Thumb targets only. No Nikon images,
camera connection, private inputs or Python dependencies are needed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time

from qemu_control import QMP, stop_child, wait_for_sockets

FIXTURES = Path(__file__).resolve().parent / 'fixtures'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def elf_text(data):
    """Extract a relocation-free .text fixture from a little-endian ELF object."""
    if data[:4] != b'\x7fELF' or data[5] != 1 or data[4] not in (1, 2):
        raise ValueError('Expected a little-endian ELF32/64 fixture')
    wide = data[4] == 2
    offset = struct.unpack_from('<Q' if wide else '<I', data, 40 if wide else 32)[0]
    size, count, names = struct.unpack_from('<HHH', data, 58 if wide else 46)
    fmt = '<IIQQQQIIQQ' if wide else '<10I'
    sections = [struct.unpack_from(fmt, data, offset + i * size) for i in range(count)]
    table = sections[names]
    strings = data[table[4]:table[4] + table[5]]
    result = None
    for index, section in enumerate(sections):
        name = strings[section[0]:].split(b'\0', 1)[0]
        if name == b'.text':
            if result is not None:
                raise ValueError('Multiple .text sections')
            result = (index, section)
    if result is None:
        raise ValueError('Missing .text section')
    if any(s[1] in (4, 9) and s[5] and s[7] == result[0] for s in sections):
        raise ValueError('Fixture .text has unresolved relocations')
    section = result[1]
    return data[section[4]:section[4] + section[5]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--clang', default=os.environ.get('CLANG', 'clang'))
    parser.add_argument('--expect-global-reset', action='store_true',
                        help='Qualify the uncorrected board as a negative control')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = dict(schema='z8-mcu-reset-controls-v1', qemu_sha256=sha(args.qemu),
                  source_sha256=sha(Path(__file__)), original_firmware_loaded=False,
                  expected_global_reset=args.expect_global_reset, cases=[], checks=[])

    def compile_program(name, target, destination, flags=()):
        source = out / name
        shutil.copy2(FIXTURES / name, source)
        obj = destination.with_suffix('.o')
        command = [args.clang, '--target=' + target, '-c', str(source), '-o', str(obj), *flags]
        subprocess.run(command, check=True, capture_output=True)
        destination.write_bytes(elf_text(obj.read_bytes()))
        return dict(command=command, source_sha256=sha(source), program_sha256=sha(destination))

    a53 = out / 'a53.bin'
    report['a53_build'] = compile_program('a53-reset-heartbeat.S', 'aarch64-none-elf', a53)
    for resets in (0, 1, 2):
        case = out / f'reset-{resets}'
        case.mkdir()
        mcu = case / 'mcu.bin'
        record = dict(resets=resets, error=None)
        process = qmp = None
        try:
            record['build'] = compile_program('mcu-reset-test.S', 'arm-none-eabi', mcu,
                ('-mcpu=cortex-m4', '-mthumb', f'-DRESET_COUNT={resets}'))
            with tempfile.TemporaryDirectory(prefix='z8-reset-') as temp:
                endpoint = Path(temp) / 'qmp'
                command = [str(args.qemu.resolve()), '-M',
                    f'nikon-z8-lab,mcu-image={mcu},bootstrap-fixtures=on,bus-window-fixture=on,serial-fixture=on,image-bank-model=on',
                    '-cpu', 'cortex-a53', '-smp', '4,maxcpus=5', '-kernel', str(a53),
                    '-accel', 'tcg,thread=single', '-display', 'none', '-serial', 'none',
                    '-monitor', 'none', '-nic', 'none', '-S', '-no-reboot',
                    '-action', 'shutdown=pause', '-qmp', f'unix:{endpoint},server=on,wait=off']
                record['command'] = command
                with (case / 'stderr.log').open('wb') as log:
                    process = subprocess.Popen(command, stdout=log, stderr=log)
                wait_for_sockets(process, endpoint)
                qmp = QMP(endpoint)
                qmp.command('cont')
                deadline = time.monotonic() + 8
                # Wait for the program's completion marker or the baseline's
                # global-reset stop. Do not assume a fixed host execution rate.
                while True:
                    time.sleep(.05)
                    status = qmp.command('query-status')
                    qmp.command('stop')
                    qmp.command('memsave', val=0x20000000, size=0x80,
                                filename=str(case / 'mcu-result.bin'), **{'cpu-index': 4})
                    words = struct.unpack('<32I', (case / 'mcu-result.bin').read_bytes())
                    if words[3] == 0x600d600d or not status['running']:
                        break
                    if time.monotonic() > deadline:
                        raise TimeoutError('M4 did not complete the synthetic reset program')
                    qmp.command('cont')
                qmp.command('pmemsave', val=0xA00010000, size=16,
                            filename=str(case / 'a53-before.bin'))
                before = struct.unpack('<2Q', (case / 'a53-before.bin').read_bytes())
                if status['running']:
                    qmp.command('cont')
                    time.sleep(.15)
                    qmp.command('stop')
                qmp.command('pmemsave', val=0xA00010000, size=16,
                            filename=str(case / 'a53-after.bin'))
                after = struct.unpack('<2Q', (case / 'a53-after.bin').read_bytes())
                record.update(status=status, words=[hex(x) for x in words],
                              a53_before=before, a53_after=after)

                def check(name, passed):
                    report['checks'].append(dict(resets=resets, name=name, passed=bool(passed)))

                global_reset = any(e.get('event') == 'SHUTDOWN' and
                    e.get('data', {}).get('reason') == 'guest-reset' for e in qmp.events)
                expected_global = args.expect_global_reset and resets > 0
                check('Global reset request matches declared baseline/candidate',
                      global_reset == expected_global)
                check('M4 reached SRAM and both AIRCR negative controls',
                      words[0] == 0x4d435552 and words[2] == words[0x58//4] == 1)
                check('Independent A53 program executed',
                      before[0] == 0x4135334845415254 and before[1] > 0)
                if not expected_global:
                    check('Guest remains running across MCU activity', status['running'])
                    check('A53 heartbeat continues after MCU control', after[1] > before[1])
                    check('M4 completed expected reset count',
                          words[1] == resets + 1 and words[3] == 0x600d600d)
                    check('M4 ordinary and backup SRAM retained',
                          words[4] == words[0x60//4] == 0xcafebabe)
                    check('Programmed MCU flash survives without image reload',
                          words[0x50//4] == 0xcafebabe)
                    check('RTC backup register retained', words[0x20//4] == 0x1234abcd)
                    check('RCC backup clock configuration retained', words[0x1c//4] == words[0x68//4])
                    expected = {0x18: 0x10000000, 0x24: 0xa8000000, 0x28: 0, 0x2c: 7,
                        0x30: 0, 0x34: 0, 0x38: 0, 0x3c: 0, 0x40: 0, 0x44: 0x2004fff0,
                        0x48: 0, 0x4c: 0, 0x54: 0x80000000} if resets else {
                        0x18: 0, 0x24: 0x28000001, 0x28: 4, 0x2c: 0x1234,
                        0x30: 0x1234, 0x34: 0x4321, 0x38: 1, 0x3c: 1000, 0x40: 0x20,
                        0x44: 0x2004fff0, 0x48: 1, 0x4c: 0, 0x54: 0x201}
                    for offset, value in expected.items():
                        check(f'Reset/control field {offset:#x} equals {value:#x}',
                              words[offset//4] == value)
                if resets == 0:
                    def switches():
                        return json.loads(qmp.command('qom-get',path='/machine',property='native-mcu-switch-state'))
                    qmp.command('qom-set',path='/machine',property='mcu-contacts',value='23.6=0:23.13=0')
                    pressed=switches()
                    expander=next(x['inputs'] for x in pressed['expanders'] if x['address']==0x23)
                    check('External expander contacts change only requested bits',expander==(0xffffff&~((1<<6)|(1<<13))))
                    rejected=False
                    try:
                        qmp.command('qom-set',path='/machine',property='mcu-contacts',value='23.6=1:ff.7=0')
                    except RuntimeError:
                        rejected=True
                    check('Invalid contact batch is rejected atomically',rejected and switches()==pressed)
                    qmp.command('qom-set',path='/machine',property='mcu-contacts',value='23.6=1:23.13=1')
                    check('External contacts release to idle',all(x['inputs']==0xffffff for x in switches()['expanders']))
                    native=json.loads(qmp.command('qom-get',path='/machine',property='native-mcu-state'))
                    check('Contact inputs fabricate no MCU messages',switches()['frames']==0 and native['main_frames']==native['mcu_frames']==0 and not native['host_message_replies'])
        except Exception as error:
            record['error'] = repr(error)
        finally:
            stop_child(process, qmp)
            record['QMP_events'] = qmp.events if qmp else []
            record['owned_QEMU_stopped'] = process is None or process.poll() is not None
            if mcu.exists() and 'build' in record:
                record['synthetic_inputs_unchanged'] = sha(a53) == report['a53_build']['program_sha256'] and \
                    sha(mcu) == record['build']['program_sha256']
            report['cases'].append(record)
            (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    failed = [x for x in report['checks'] if not x['passed']]
    errors = [x['error'] for x in report['cases'] if x['error']]
    print(json.dumps(dict(output=str(out), checks=len(report['checks']), failed=failed, errors=errors,
                         cleanup=all(x['owned_QEMU_stopped'] for x in report['cases']))))
    return 1 if failed or errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
