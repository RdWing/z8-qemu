# SPDX-License-Identifier: GPL-2.0-or-later
"""Recognize the verified C3.11 terminal SRAM park, without changing CPU state."""
TERMINAL_PARKS = {0: (0x082012F4, 0x082012F8),
                  1: (0x08201350, 0x08201354),
                  2: (0x082013AC, 0x082013B0)}

def powered_down(clock, ui_mode):
    if ui_mode != 0:
        return False
    cpus = {cpu.get('index'): cpu for cpu in clock.get('cpus', [])}
    return all(index in cpus and cpus[index].get('halted') is True and
               cpus[index].get('pc') in addresses
               for index, addresses in TERMINAL_PARKS.items())
