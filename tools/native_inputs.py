# SPDX-License-Identifier: GPL-2.0-or-later
"""Z8 external contacts qualified through original EX 124-byte switch reports."""
from control import BUTTONS
from native_dials import Dial

CONTACTS={'menu':('mcu-contacts','23.6'),'down':('mcu-contacts','23.13'),
          'ok':('mcu-contacts','23.11'),'left':('mcu-contacts','23.12'),
          'up':('mcu-contacts','23.15'),'right':('mcu-contacts','23.14'),
          'i':('mcu-contacts','23.7'),'half':('mcu-pins','G1'),
          'play':('mcu-contacts','23.5'),'disp':('mcu-contacts','23.8'),
          'protect':('mcu-contacts','23.9'),'delete':('mcu-contacts','23.18')}

class Inputs:
    def __init__(self,qmp,*,allow_modes=False,allow_capture=False):
        self.qmp=qmp;self.allow_modes=allow_modes;self.held=None;self.release_at=0;self.next_at=0
        self.allow_capture=allow_capture;self.capture=None;self.dial=None
        self.by_offset={BUTTONS[name]:binding for name,binding in CONTACTS.items()}
    def release(self):
        if self.dial:
            self.dial.release();self.dial=None
        if self.capture:
            self.qmp.command('qom-set',path='/machine',property='mcu-pins',value='G1=1:G13=1')
            self.qmp.command('qom-set',path='/machine',property='capture-gpio-input',value='0')
            self.capture['control'].finish_capture('Capture inputs cancelled.')
            self.capture=None
        if self.held:
            prop,contact=self.held
            self.qmp.command('qom-set',path='/machine',property=prop,value=contact+'=1')
            self.held=None
    def tick(self,control,virtual_seconds):
        if self.dial:
            event=self.dial.tick(virtual_seconds)
            if self.dial.finished:self.dial=None;self.next_at=virtual_seconds+.25
            return event
        if self.capture:
            current=self.capture
            actions=((0,'G1=0','1'),(2,'G13=0','3'),(6,'G13=1','1'),(8,'G1=1','0'))
            if current['phase']<len(actions) and virtual_seconds>=current['at']+actions[current['phase']][0]:
                _,pins,main=actions[current['phase']]
                self.qmp.command('qom-set',path='/machine',property='mcu-pins',value=pins)
                self.qmp.command('qom-set',path='/machine',property='capture-gpio-input',value=main)
                current['phase']+=1
                return dict(kind='capture-contact',mcu_pins=pins,main_capture_gpio=main,virtual_seconds=virtual_seconds)
            if current['phase']==4 and control.capture_completed_jobs>current['before']:
                control.finish_capture();self.capture=None;self.next_at=virtual_seconds+1
                return dict(kind='capture-complete',virtual_seconds=virtual_seconds)
            if virtual_seconds>=current['at']+20:
                self.release();control.finish_capture('Capture outcome is not confirmed. Check the camera display before retrying.')
                self.next_at=virtual_seconds+1
                return dict(kind='capture-timeout',virtual_seconds=virtual_seconds)
            return None
        if self.held and virtual_seconds>=self.release_at:
            self.release();self.next_at=virtual_seconds+.25
        if self.held or virtual_seconds<self.next_at:return None
        action=control.next_input()
        if action is None:return None
        kind,value=action
        if kind=='dial':
            self.dial=Dial(self.qmp,*value,virtual_seconds)
            event=self.dial.tick(virtual_seconds);control.mark_sent()
            return event
        if kind=='capture':
            if not self.allow_capture:raise ValueError('Native capture profile is not enabled')
            self.capture={'at':virtual_seconds,'phase':0,'before':control.capture_completed_jobs,'control':control}
            control.mark_sent()
            return self.tick(control,virtual_seconds)
        if kind=='mode' and self.allow_modes and value in ('photo','movie'):
            level=0 if value=='movie' else 1
            self.qmp.command('qom-set',path='/machine',property='mcu-contacts',value='23.10='+str(level))
            self.next_at=virtual_seconds+2;control.shooting_mode=value;control.mark_sent()
            return dict(kind=kind,value=value,property='mcu-contacts',contact='23.10',level=level,virtual_seconds=virtual_seconds)
        if kind!='button' or value not in self.by_offset:
            raise ValueError('Native input has no qualified Z8 contact')
        prop,contact=self.by_offset[value]
        self.qmp.command('qom-set',path='/machine',property=prop,value=contact+'=0')
        self.held=(prop,contact);self.release_at=virtual_seconds+.25
        control.mark_sent()
        return dict(kind=kind,value=value,property=prop,contact=contact,virtual_seconds=virtual_seconds)
