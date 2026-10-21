# SPDX-License-Identifier: GPL-2.0-or-later
"""Timed external GPIO/expander inputs; no firmware memory or message writes."""
import json
import math
from pathlib import Path
import re

PATTERNS={'mcu-pins':r'[A-K](?:[0-9]|1[0-5])=[01]',
          'mcu-contacts':r'(?:22|23)\.(?:[0-9]|1[0-9]|2[0-3])=[01]',
          'capture-gpio-input':r'[0-3]'}

class ContactReplay:
    def __init__(self,path):
        self.actions=json.loads(Path(path).read_text());self.next=0
        if not isinstance(self.actions,list) or not 1<=len(self.actions)<=128:
            raise ValueError('Expected 1..128 external contact actions')
        previous=0
        for row in self.actions:
            if not isinstance(row,dict) or set(row)!={'at','property','value'}:
                raise ValueError('Contact action requires at, property and value')
            at=row['at'];prop=row['property'];value=row['value']
            if type(at) not in (int,float) or not math.isfinite(at) or not previous<=at<=3600:
                raise ValueError('Contact times must be finite, ordered and within 0..3600')
            if prop not in PATTERNS or not isinstance(value,str) or not 1<=len(value)<=1024 or not all(
                re.fullmatch(PATTERNS[prop],item) for item in ([value] if prop=='capture-gpio-input' else value.split(':'))):
                raise ValueError('Expected explicit MCU/MAIN GPIO or expander contacts only')
            previous=at
    def dispatch(self,qmp,virtual_seconds):
        sent=[]
        while self.next<len(self.actions) and self.actions[self.next]['at']<=virtual_seconds:
            row=self.actions[self.next]
            qmp.command('qom-set',path='/machine',property=row['property'],value=row['value'])
            sent.append(dict(row,delivered_at=virtual_seconds));self.next+=1
        return sent
