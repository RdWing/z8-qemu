# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Read-only original Z8 exception observations before a diagnostic MMIO fault."""
import re
from service_z8_mcu import Peer as BasePeer

class Peer(BasePeer):
    OBSERVERS = {0x40c7d858: 'audio-start-return',
                 0x40c07b30: 'register-dump-entry',
                 0x40c032e8: 'exception-context',
                 0x40c036b8: 'full-exception'}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for pc, label in self.OBSERVERS.items():
            self.arm(pc, label)
    def handle(self):
        for cpu in range(4):
            regs = {k: int(v, 16) for k, v in re.findall(
                r'\b(X\d\d|PC|SP)=([0-9a-fA-F]+)',
                self.g.qmp.hmp('info registers', cpu))}
            pc = regs['PC']
            if pc not in self.OBSERVERS or pc not in self.points:
                continue
            row = dict(label=self.OBSERVERS[pc], cpu=cpu,
                       registers={k: hex(v) for k, v in regs.items()})
            # Observe RAM only. Never probe unknown MMIO on the failure path.
            for name, address, amount in [('stack', regs['SP'], 2048),
                                          ('context', regs['X19'], 512)]:
                if 0xa00000000 <= address <= 0xa20000000-amount:
                    row[name+'_hex'] = self.g.read_bytes(address, amount).hex()
            self.g.data.setdefault('transition_observers', []).append(row)
        return super().handle()
