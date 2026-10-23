# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""One finite external quadrature cycle; original EX owns dial reports."""
import json

# Target EX descriptor slots 4/5 and 2/3, independently joined to reports 0B/0C.
PINS = {'main': (4, 7, 13), 'sub': (5, 11, 14)}
GRAY = (0, 1, 3, 2)
PHASE_SECONDS = .08


class Dial:
    def __init__(self, qmp, axis, direction, virtual_seconds):
        if axis not in PINS or type(direction) is not int or direction not in (-1, 1):
            raise ValueError('Expected main/sub dial and signed one-step direction')
        self.qmp = qmp; self.axis = axis; self.direction = direction
        self.port, self.pin_a, self.pin_b = PINS[axis]
        state = json.loads(qmp.command('qom-get', path='/machine', property='native-mcu-io-state'))
        if not state.get('enabled'):
            raise ValueError('Dial inputs require original EX')
        gpio = next(row for row in state['gpio'] if row['port'] == self.port)
        self.origin = (((gpio['input'] >> self.pin_a) & 1) << 1) | ((gpio['input'] >> self.pin_b) & 1)
        self.phase = 0; self.next_at = virtual_seconds; self.finished = False

    def drive(self, value):
        port = chr(ord('A') + self.port)
        pins = f'{port}{self.pin_a}={value >> 1}:{port}{self.pin_b}={value & 1}'
        self.qmp.command('qom-set', path='/machine', property='mcu-pins', value=pins)
        return pins

    def tick(self, virtual_seconds):
        if self.finished or virtual_seconds < self.next_at:
            return None
        # EX counts one selected edge per cycle. Reverse Gray order gives +1
        # in both target report fields; direction means report sign, not CW.
        index = (GRAY.index(self.origin) - self.direction * (self.phase + 1)) % 4
        pins = self.drive(GRAY[index])
        self.phase += 1; self.next_at = virtual_seconds + PHASE_SECONDS
        self.finished = self.phase == 4
        return dict(kind='dial-contact', axis=self.axis, direction=self.direction,
                    phase=self.phase, mcu_pins=pins, virtual_seconds=virtual_seconds)

    def release(self):
        if not self.finished:
            self.drive(self.origin)
            self.finished = True


MODIFIERS = {'mode': '22.5', 'compensation': '22.3'}


class ModifiedDial:
    """One Main turn inside a finite qualified button hold."""
    def __init__(self, qmp, modifier, direction, virtual_seconds):
        if modifier not in MODIFIERS:
            raise ValueError('Expected a qualified dial modifier')
        self.qmp = qmp; self.modifier = modifier; self.contact = MODIFIERS[modifier]
        self.dial = Dial(qmp, 'main', direction, virtual_seconds + .25)
        self.finished = False; self.release_at = None
        qmp.command('qom-set', path='/machine', property='mcu-contacts', value=self.contact+'=0')

    def tick(self, virtual_seconds):
        if self.finished:
            return None
        if self.release_at is not None:
            if virtual_seconds < self.release_at:
                return None
            self.release()
            return dict(kind=self.modifier+'-dial-release', virtual_seconds=virtual_seconds)
        event = self.dial.tick(virtual_seconds)
        if event:
            event['modifier'] = self.modifier
        if self.dial.finished:
            self.release_at = virtual_seconds + .25
        return event

    def release(self):
        if not self.finished:
            try:
                self.dial.release()
            finally:
                self.qmp.command('qom-set', path='/machine', property='mcu-contacts', value=self.contact+'=1')
                self.finished = True
