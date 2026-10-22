# SPDX-License-Identifier: GPL-2.0-or-later
"""Finite external dial cycles preserve EX edge counts and queue ownership."""
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from native_dials import Dial, ModifiedDial, PINS, MODIFIERS
from native_inputs import Inputs


class QMP:
    def __init__(self, axis='main', origin=3):
        self.axis=axis;self.value=origin;self.values=[];self.count=0
    def command(self, name, **kw):
        if name=='qom-get':
            port,a,b=PINS[self.axis]
            return json.dumps(dict(enabled=True,gpio=[dict(port=port,input=((self.value>>1)<<a)|((self.value&1)<<b))]))
        self.values.append(kw['value'])
        a,b=kw['value'].split(':');now=(int(a[-1])<<1)|int(b[-1])
        # Independent target EX counter rules: only the selected edge counts.
        positive,negative=((0,2),(2,0)) if self.axis=='main' else ((1,0),(0,1))
        if (self.value,now)==positive:self.count+=1
        if (self.value,now)==negative:self.count-=1
        self.value=now


class NativeDials(unittest.TestCase):
    def test_each_axis_sign_and_initial_phase_yield_exactly_one_count(self):
        for axis in PINS:
            for origin in range(4):
                for sign in (-1,1):
                    with self.subTest(axis=axis,origin=origin,sign=sign):
                        q=QMP(axis,origin);dial=Dial(q,axis,sign,10)
                        previous=origin
                        for at in (10,10.1,10.2,10.3):
                            row=dial.tick(at)
                            self.assertEqual(row['direction'],sign)
                            self.assertIn(previous^q.value,(1,2));previous=q.value
                        self.assertTrue(dial.finished);self.assertEqual(q.value,origin)
                        self.assertEqual(q.count,sign);self.assertEqual(len(q.values),4)
                        self.assertIsNone(dial.tick(11));dial.release();self.assertEqual(len(q.values),4)

    def test_late_tick_does_not_collapse_remaining_phases(self):
        q=QMP();dial=Dial(q,'main',1,0)
        dial.tick(0);self.assertIsNone(dial.tick(.01))
        dial.tick(3);self.assertIsNone(dial.tick(3.01))
        self.assertEqual(len(q.values),2);self.assertFalse(dial.finished)
        dial.release();dial.release();self.assertEqual(q.value,3);self.assertEqual(len(q.values),3)

    def test_input_owner_keeps_later_key_and_capture_queued(self):
        q=QMP()
        class Control:
            sent=0
            def __init__(self):self.actions=[('dial',('main',1)),('button',67),('capture',None)]
            def next_input(self):return self.actions.pop(0) if self.actions else None
            def mark_sent(self):self.sent+=1
        c=Control();inputs=Inputs(q)
        for at in (0,.1,.2,.3):self.assertEqual(inputs.tick(c,at)['kind'],'dial-contact')
        self.assertEqual(c.sent,1);self.assertEqual(len(c.actions),2)
        self.assertIsNone(inputs.tick(c,.4))
        # Stop/release during a later dial restores its original phase once.
        c.actions=[('dial',('main',-1))];inputs.tick(c,1)
        inputs.release();n=len(q.values);inputs.release();self.assertEqual(len(q.values),n)
        self.assertEqual(q.value,3)


class ModifiedDialOwnership(unittest.TestCase):
    class Contacts(QMP):
        def __init__(self):
            super().__init__();self.level=1;self.contacts=[];self.contact_ids=[]
        def command(self,name,**kw):
            if name=='qom-set' and kw['property']=='mcu-contacts':
                self.level=int(kw['value'][-1]);self.contacts.append(self.level);self.contact_ids.append(kw['value'].split('=')[0])
                return
            return super().command(name,**kw)

    def test_hold_settles_then_turns_then_releases_before_next_input(self):
        for modifier in MODIFIERS:
            with self.subTest(modifier=modifier):self.assert_hold(modifier)

    def assert_hold(self,modifier):
        q=self.Contacts()
        class Control:
            def __init__(self):self.actions=[(modifier+'-dial',1),('button',67)];self.sent=0
            def next_input(self):return self.actions.pop(0) if self.actions else None
            def mark_sent(self):self.sent+=1
        c=Control();inputs=Inputs(q)
        self.assertEqual(inputs.tick(c,0)['kind'],modifier+'-dial-hold')
        self.assertEqual(q.level,0);self.assertIsNone(inputs.tick(c,.24))
        for at in (.25,.35,.45,.55):
            self.assertEqual(inputs.tick(c,at)['modifier'],modifier)
            self.assertEqual(q.level,0);self.assertEqual(len(c.actions),1)
        self.assertIsNone(inputs.tick(c,.79))
        self.assertEqual(inputs.tick(c,.81)['kind'],modifier+'-dial-release')
        self.assertEqual(q.level,1);self.assertEqual(q.count,1)
        self.assertEqual(c.sent,1);self.assertEqual(len(c.actions),1)
        self.assertIsNone(inputs.tick(c,1))

    def test_cancel_at_every_phase_restores_both_inputs_once(self):
        for modifier in MODIFIERS:
            for phases in range(5):
                with self.subTest(modifier=modifier,phases=phases):
                    q=self.Contacts();chord=ModifiedDial(q,modifier,-1,0)
                    for n in range(phases):chord.tick(.25+n*.1)
                    chord.release();self.assertTrue(chord.finished)
                    self.assertEqual(q.level,1);self.assertEqual(q.value,3)
                    self.assertEqual(q.contact_ids,[MODIFIERS[modifier]]*2)
                    count=(len(q.values),len(q.contacts))
                    chord.release();self.assertEqual(count,(len(q.values),len(q.contacts)))
                    self.assertIsNone(chord.tick(10))
        q=self.Contacts()
        with self.assertRaises(ValueError):ModifiedDial(q,'unknown',1,0)
        self.assertEqual(q.contacts,[]);self.assertEqual(q.values,[])
