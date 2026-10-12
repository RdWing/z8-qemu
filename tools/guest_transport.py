# SPDX-License-Identifier: GPL-2.0-or-later
import json
import socket
import subprocess
import time
from probe import QMP

class Transport:
    def __enter__(self):
        try:
            with self.log_path.open('wb') as log:
                self.proc = subprocess.Popen(self.command, stdout=subprocess.DEVNULL, stderr=log)
            deadline = time.monotonic()+10
            while not (self.runtime/'qtest.sock').exists():
                if self.proc.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('QEMU startup failed')
                time.sleep(.02)
            self.qmp = QMP(self.runtime/'qmp.sock')
            self.qt = socket.socket(socket.AF_UNIX)
            self.qt.settimeout(3)
            self.qt.connect(str(self.runtime/'qtest.sock'))
            self.fp = self.qt.makefile('rwb', buffering=0)
            if self.accelerator != 'qtest':
                self.gdb = socket.socket(socket.AF_UNIX)
                self.gdb.settimeout(3)
                self.gdb.connect(str(self.runtime/'gdb.sock'))
            if self.intercept_irq:
                children = self.qmp.command('qom-list', path='/machine/unattached')
                gics = [x for x in children if x['type'] == 'child<arm-gicv3>']
                if len(gics) != 1:
                    raise RuntimeError('GIC object not unique')
                self.qt_command('irq_intercept_in /machine/unattached/'+gics[0]['name'])
            if self.accelerator != 'qtest':
                self.rsp('Z1,40160000,4')
            return self
        except BaseException as exc:
            self.__exit__(type(exc), exc, None)
            raise

    def qt_command(self, command):
        self.fp.write(command.encode()+b'\n')
        while True:
            reply = self.fp.readline().decode().strip()
            if not reply.startswith('IRQ '):
                break
            _, action, number = reply.split()
            self.irq[int(number)] = action == 'raise'
            self.data['irq_events'].append(reply)
        if not reply.startswith('OK'):
            raise RuntimeError(f'{command}: {reply}')
        return reply.split()[1:]

    def rd(self, address):
        return int(self.qt_command(f'readl {address:#x}')[0], 0)

    def wr(self, address, value):
        self.qt_command(f'writel {address:#x} {value:#x}')

    def read_bytes(self, address, size):
        return bytes.fromhex(self.qt_command(f'read {address:#x} {size:#x}')[0][2:])

    def log(self):
        return self.log_path.read_text()

    def check(self, name, condition):
        self.data['checks'].append(dict(name=name, passed=bool(condition)))
        if not condition:
            raise AssertionError(name)

    def rsp(self, command, *, expect_ok=True, accept_stop=False):
        body = command.encode()
        self.gdb.sendall(b'$'+body+b'#'+f'{sum(body)&255:02x}'.encode())
        while True:
            char = self.gdb.recv(1)
            while char != b'$':
                if not char:
                    raise EOFError('GDB disconnected')
                char = self.gdb.recv(1)
            reply = bytearray()
            while True:
                char = self.gdb.recv(1)
                if char == b'#':
                    break
                if not char:
                    raise EOFError('GDB disconnected in packet')
                reply += char
            checksum = b''
            while len(checksum) < 2:
                char = self.gdb.recv(2-len(checksum))
                if not char:
                    raise EOFError('GDB disconnected at checksum')
                checksum += char
            if checksum != f'{sum(reply)&255:02x}'.encode():
                raise RuntimeError('bad GDB checksum')
            self.gdb.sendall(b'+')
            if reply.startswith((b'T', b'S')) and not accept_stop:
                if hasattr(self, 'rsp_stop_packets'):
                    self.rsp_stop_packets.append(reply.decode('ascii'))
                continue
            if expect_ok and reply != b'OK':
                raise RuntimeError(f'{command}: {reply!r}')
            return None if expect_ok else reply.decode('ascii')
