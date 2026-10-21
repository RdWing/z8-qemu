# SPDX-License-Identifier: GPL-2.0-or-later
"""Check export/image-lock exclusion with a firmware-free, stopped QEMU VM."""
import argparse
import hashlib
import json
from pathlib import Path
import select
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from desktop_photo_export import card_read_lease


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    card = args.output.resolve()/'card.raw'
    card.write_bytes(bytes(1024*1024))
    before = hashlib.sha256(card.read_bytes()).hexdigest()
    command = [str(args.qemu.resolve()), '-M', 'virt', '-cpu', 'cortex-a53', '-m', '128M',
               '-S', '-nodefaults', '-display', 'none', '-serial', 'none', '-monitor', 'none',
               '-qmp', 'stdio', '-drive', f'file={card},format=raw,if=none,id=card,file.locking=on',
               '-device', 'virtio-blk-device,drive=card']
    def start():
        return subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, bufsize=0)
    def ready(process):
        def read():
            if not select.select([process.stdout], [], [], 10)[0]:
                raise RuntimeError('QEMU initialization deadline')
            line = process.stdout.readline()
            if not line: raise RuntimeError('QEMU exited before initialization')
            return json.loads(line)
        if 'QMP' not in read(): raise RuntimeError('Expected QMP greeting')
        for name in ('qmp_capabilities', 'query-status'):
            process.stdin.write(json.dumps(dict(execute=name)).encode()+b'\n')
            while True:
                response = read()
                if 'error' in response: raise RuntimeError(response['error'])
                if 'return' in response: break
        # The greeting alone precedes block initialization and is insufficient.
    def stop(process):
        if process.poll() is None: process.terminate()
        try: process.communicate(timeout=10)
        except subprocess.TimeoutExpired: process.kill(); process.communicate()
    process = start()
    try:
        ready(process)
        try:
            with card_read_lease(card): raise AssertionError('Active QEMU writer admitted')
        except ValueError as error:
            if 'in use' not in str(error): raise
    finally: stop(process)
    with card_read_lease(card):
        process = start()
        try:
            _, error = process.communicate(timeout=10)
            if process.returncode == 0 or b'lock' not in error.lower():
                raise AssertionError('New QEMU writer was not excluded')
        finally: stop(process)
    process = start()
    try: ready(process)
    finally: stop(process)
    if hashlib.sha256(card.read_bytes()).hexdigest() != before:
        raise AssertionError('Firmware-free lock checks changed the card')
    result = dict(checks=4, active_writer_excluded=True, new_writer_excluded=True,
                  writer_after_release=True, card_unchanged=True, owned_cleanup=True)
    (args.output/'result.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result))


if __name__ == '__main__': main()
