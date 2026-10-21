# SPDX-License-Identifier: GPL-2.0-or-later
"""Native buttons own an external contact through press/release/cooldown."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from native_inputs import Inputs

class NativeInputs(unittest.TestCase):
    def test_virtual_press_release_and_queue_ownership(self):
        class QMP:
            def __init__(self):self.calls=[]
            def command(self,name,**kw):self.calls.append((name,kw))
        class Control:
            def __init__(self):self.actions=[('button',67),('button',7)];self.sent=0
            def next_input(self):return self.actions.pop(0) if self.actions else None
            def mark_sent(self):self.sent+=1
        qmp=QMP();control=Control();inputs=Inputs(qmp)
        first=inputs.tick(control,1);self.assertEqual(first['contact'],'23.6')
        self.assertEqual(qmp.calls[-1][1]['value'],'23.6=0');self.assertEqual(control.sent,1)
        self.assertIsNone(inputs.tick(control,1.1));self.assertEqual(len(qmp.calls),1)
        inputs.tick(control,1.25);self.assertEqual(qmp.calls[-1][1]['value'],'23.6=1')
        self.assertEqual(len(control.actions),1)
        inputs.tick(control,1.5);self.assertEqual(qmp.calls[-1][1]['value'],'G1=0');self.assertEqual(control.sent,2)
        inputs.release();self.assertEqual(qmp.calls[-1][1]['value'],'G1=1')
        before=len(qmp.calls);inputs.release();self.assertEqual(len(qmp.calls),before)
