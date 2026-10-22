# Copyright (C) 2026 RdWing: Z8 adaptation.
# SPDX-License-Identifier: GPL-2.0-or-later
"""Small synchronous QMP client for the synthetic board checks."""
import json
import socket
import subprocess
import time


class QMP:
    def __init__(self, path):
        self.socket = socket.socket(socket.AF_UNIX)
        self.socket.settimeout(3)
        self.socket.connect(str(path))
        self.stream = self.socket.makefile('rwb', buffering=0)
        self.events = []
        self.sequence = 0
        greeting = json.loads(self.stream.readline())
        if 'QMP' not in greeting:
            raise RuntimeError(f'Invalid QMP greeting: {greeting}')
        self.command('qmp_capabilities')

    def command(self, name, **arguments):
        self.sequence += 1
        request = {'execute': name, 'arguments': arguments, 'id': self.sequence}
        self.stream.write(json.dumps(request).encode() + b'\n')
        while True:
            line = self.stream.readline()
            if not line:
                raise EOFError('QMP disconnected')
            item = json.loads(line)
            if 'event' in item:
                self.events.append(item)
                continue
            if item.get('id') != self.sequence:
                raise RuntimeError(f'Unexpected QMP response: {item}')
            if 'error' in item:
                raise RuntimeError(item['error'])
            return item['return']

    def close(self):
        self.stream.close()
        self.socket.close()


def wait_for_sockets(process, *paths):
    deadline = time.monotonic() + 8
    while not all(path.exists() for path in paths):
        if process.poll() is not None:
            raise RuntimeError(f'QEMU exited with status {process.returncode}')
        if time.monotonic() > deadline:
            raise TimeoutError('QEMU control sockets did not appear')
        time.sleep(.02)


def stop_child(process, qmp):
    """Reap only the child launched by this check, even after a QMP failure."""
    if process is not None and process.poll() is None:
        try:
            if qmp is not None:
                qmp.command('quit')
            process.wait(timeout=3)
        except (OSError, EOFError, ValueError, RuntimeError,
                subprocess.TimeoutExpired):
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
    if qmp is not None:
        qmp.close()
