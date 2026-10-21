# SPDX-License-Identifier: GPL-2.0-or-later
"""Z8 external contacts qualified through original EX 124-byte switch reports."""
from control import BUTTONS

CONTACTS={'menu':('mcu-contacts','23.6'),'down':('mcu-contacts','23.13'),
          'ok':('mcu-contacts','23.11'),'left':('mcu-contacts','23.12'),
          'up':('mcu-contacts','23.15'),'right':('mcu-contacts','23.14'),
          'i':('mcu-contacts','23.7'),'half':('mcu-pins','G1')}

class Inputs:
    def __init__(self,qmp):
        self.qmp=qmp;self.held=None;self.release_at=0;self.next_at=0
        self.by_offset={BUTTONS[name]:binding for name,binding in CONTACTS.items()}
    def release(self):
        if self.held:
            prop,contact=self.held
            self.qmp.command('qom-set',path='/machine',property=prop,value=contact+'=1')
            self.held=None
    def tick(self,control,virtual_seconds):
        if self.held and virtual_seconds>=self.release_at:
            self.release();self.next_at=virtual_seconds+.25
        if self.held or virtual_seconds<self.next_at:return None
        action=control.next_input()
        if action is None:return None
        kind,value=action
        if kind!='button' or value not in self.by_offset:
            raise ValueError('Native input has no qualified Z8 contact')
        prop,contact=self.by_offset[value]
        self.qmp.command('qom-set',path='/machine',property=prop,value=contact+'=0')
        self.held=(prop,contact);self.release_at=virtual_seconds+.25
        control.mark_sent()
        return dict(kind=kind,value=value,property=prop,contact=contact,virtual_seconds=virtual_seconds)
