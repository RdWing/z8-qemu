# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Full external MCU records for original Z8 menu navigation.

Offsets and consumer masks are bound by check_z8_navigation_decoder.py;
native UI selection must still be verified from the resulting LCD.
No setting RAM edits or native instruction changes are used.
"""
import struct

BINDINGS = {
    'right': (0x22, 0x80, 0),
    'left': (0x23, 0x40, 0),
    'up': (0x24, 0x20, 0),
    'down': (0x25, 0x10, 0),
    'menu': (0x43, 0, 0x8000),
    'ok': (0x4a, 0, 1),
}


def parse_actions(text):
    if not text:
        return []
    actions = text.lower().split(',')
    if not 1 <= len(actions) <= 32 or any(x not in BINDINGS for x in actions):
        raise ValueError('1..32 comma-separated menu/right/left/up/down/ok actions required')
    return actions


def states(actions):
    def record(label, binding=None):
        body = bytearray(124)
        body[0] = body[4] = 1
        sw0, sw1 = 0x200, 0
        if binding is not None:
            byte, mask0, mask1 = binding
            body[byte] = 1
            sw0 |= mask0
            sw1 |= mask1
        return dict(label=label, body_hex=body.hex(),
                    expected_hex=struct.pack('<11I', sw0, sw1, *([0]*9)).hex())
    output = [record('navigation-initial-release')]
    for action in actions:
        output.append(record('navigation-'+action+'-press', BINDINGS[action]))
        output.append(record('navigation-'+action+'-release'))
    return output
