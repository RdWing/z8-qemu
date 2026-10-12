# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
import re
import time

def at(g, pc, *, preferred_x19=None):
    g.rsp(f'Z1,{pc:x},4')
    deadline = time.monotonic() + (8 if pc in (0x40c161f0,0x40c161d8) else 30)
    expired = False
    while True:
        g.qmp.command('cont')
        while g.qmp.command('query-status')['running']:
            if time.monotonic() >= deadline:
                g.qmp.command('stop')
                expired = True
                break
            time.sleep(.01)
        early = getattr(g,'early_shutdown_observer',None)
        handled = early.handle() if early and not expired and 'Z8_UNKNOWN' not in g.log() else False
        states = [g.qmp.hmp('info registers',cpu) for cpu in range(4)]
        wanted = any(int(re.search(r'\bPC=([0-9a-fA-F]+)',s)[1],16)==pc for s in states)
        if wanted or not handled or expired:
            break
    g.data.setdefault('stops', []).append(dict(expected_pc=hex(pc), timeout=expired, registers=states))
    if expired:
        raise TimeoutError('native ADC breakpoint ' + hex(pc))
    matches = []
    for cpu, text in enumerate(states):
        regs = {k: int(v, 16) for k, v in re.findall(r'\b(X\d\d|PC|SP)=([0-9a-fA-F]+)', text)}
        if regs['PC'] == pc:
            matches.append((cpu, regs))
    if preferred_x19 is not None:
        selected = [(cpu, regs) for cpu, regs in matches if regs['X19'] == preferred_x19]
        if selected:
            # Concurrent channels may stop at the same shared PIO instruction.
            # Preserve all CPU states above, then select the actual channel
            # object; two hits for that SAME object remain ambiguous.
            g.data['stops'][-1]['preferred_x19'] = hex(preferred_x19)
            g.data['stops'][-1]['matching_cpus'] = [cpu for cpu, _ in selected]
            matches = selected
    if len(matches) != 1 or 'Z8_UNKNOWN' in g.log():
        raise RuntimeError('expected unique ADC stop without unknown MMIO')
    g.rsp(f'z1,{pc:x},4')
    return matches[0]
