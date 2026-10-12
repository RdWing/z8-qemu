# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Filter shared native PIO instruction stops by the original channel object."""
from pathlib import Path
from probe import sha
from probe_adc_capture import at


def at_channel(g, pc, channel, record, *, bindings=None):
    points = (0x40c14a60, 0x40c14a8c, 0x40c14ad0) if bindings is None else tuple(
        bindings[n] for n in ('serial_before_enable','serial_prefill','serial_drain'))
    base = 0xa02808780 if bindings is None else bindings['serial_objects']
    if pc not in points or not 0 <= channel < 11:
        raise ValueError('unverified serial observation point or channel')
    source = Path(__file__)
    record['channel_observer_sha256'] = sha(source)
    copy = g.out/'serial-channel-observer-source.py'
    if not copy.exists():
        copy.write_bytes(source.read_bytes())
    elif sha(copy) != record['channel_observer_sha256']:
        raise RuntimeError('observer source changed during guest run')
    for _ in range(16):
        cpu, regs = at(g, pc, preferred_x19=base+channel*0x68)
        if regs['X19'] == base+channel*0x68:
            return cpu, regs
        row = dict(cpu=cpu, requested_channel=channel, registers=regs)
        record.setdefault('other_channel_stops', []).append(row)
        # at() removed the breakpoint. Drain earlier stop packets with an
        # acknowledged command, then execute only this CPU's one instruction.
        # This is normal debug stepping, not a PC/register replacement.
        g.rsp(f'Hg{cpu+1:x}')
        stop = g.rsp(f'vCont;s:{cpu+1:x}', expect_ok=False, accept_stop=True)
        if not stop.startswith(('T', 'S')):
            raise RuntimeError('single-step did not produce a debug stop')
        after = g.qmp.hmp('info registers', cpu)
        row.update(single_step_stop=stop, registers_after_step=after)
        if f'PC={pc:016x}' in after:
            raise RuntimeError('unrelated serial instruction did not advance')
    raise RuntimeError('bounded serial observation exceeded unrelated stops')
