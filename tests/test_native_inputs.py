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
            def __init__(self):self.actions=[('button',67),('button',7),('button',83)];self.sent=0
            def next_input(self):return self.actions.pop(0) if self.actions else None
            def mark_sent(self):self.sent+=1
        qmp=QMP();control=Control();inputs=Inputs(qmp)
        first=inputs.tick(control,1);self.assertEqual(first['contact'],'23.6')
        self.assertEqual(qmp.calls[-1][1]['value'],'23.6=0');self.assertEqual(control.sent,1)
        self.assertIsNone(inputs.tick(control,1.1));self.assertEqual(len(qmp.calls),1)
        inputs.tick(control,1.25);self.assertEqual(qmp.calls[-1][1]['value'],'23.6=1')
        self.assertEqual(len(control.actions),2)
        inputs.tick(control,1.5);self.assertEqual(qmp.calls[-1][1]['value'],'G1=0');self.assertEqual(control.sent,2)
        inputs.release();self.assertEqual(qmp.calls[-1][1]['value'],'G1=1')
        before=len(qmp.calls);inputs.release();self.assertEqual(len(qmp.calls),before)
        self.assertEqual(inputs.tick(control,2)['contact'],'23.8')
        self.assertEqual(qmp.calls[-1][1]['value'],'23.8=0')
        inputs.tick(control,2.25);self.assertEqual(qmp.calls[-1][1]['value'],'23.8=1')

    def test_review_contacts_release_without_repeating_or_changing_other_keys(self):
        class QMP:
            def __init__(self):self.values=[]
            def command(self,name,**kw):self.values.append((kw['property'],kw['value']))
        class Control:
            def __init__(self):self.actions=[('button',73),('button',69)];self.sent=0
            def next_input(self):return self.actions.pop(0) if self.actions else None
            def mark_sent(self):self.sent+=1
        qmp=QMP();control=Control();inputs=Inputs(qmp)
        inputs.tick(control,1);inputs.tick(control,1.25)
        inputs.tick(control,1.5);inputs.release();inputs.release()
        self.assertEqual(qmp.values,[('mcu-contacts','23.9=0'),('mcu-contacts','23.9=1'),
                                     ('mcu-contacts','23.18=0'),('mcu-contacts','23.18=1')])
        self.assertEqual(control.sent,2)

    def test_mode_contact_stays_latched_through_button_release(self):
        class QMP:
            def __init__(self):self.values=[]
            def command(self,name,**kw):self.values.append((kw['property'],kw['value']))
        class Control:
            def __init__(self):self.actions=[('mode','movie'),('button',67),('mode','photo')];self.sent=0
            def next_input(self):return self.actions.pop(0) if self.actions else None
            def mark_sent(self):self.sent+=1
        qmp=QMP();control=Control();inputs=Inputs(qmp,allow_modes=True)
        inputs.tick(control,1);self.assertEqual(qmp.values,[('mcu-contacts','23.10=0')])
        self.assertIsNone(inputs.tick(control,2));inputs.tick(control,3)
        inputs.tick(control,3.25)
        self.assertEqual(qmp.values[-1],('mcu-contacts','23.6=1'))
        self.assertEqual(control.shooting_mode,'movie')
        inputs.tick(control,3.5);self.assertEqual(qmp.values[-1],('mcu-contacts','23.10=1'))
        self.assertEqual(control.shooting_mode,'photo');self.assertEqual(control.sent,3)
        rejected=Inputs(qmp);control.actions=[('mode','movie')]
        before=len(qmp.values)
        with self.assertRaises(ValueError):rejected.tick(control,4)
        self.assertEqual(len(qmp.values),before)

    def test_capture_lease_completion_timeout_and_cancellation(self):
        class QMP:
            def __init__(self):self.values=[]
            def command(self,name,**kw):self.values.append((kw['property'],kw['value']))
        class Control:
            def __init__(self):self.actions=[('capture',None),('button',67)];self.sent=0;self.capture_completed_jobs=0;self.capture_retired=False;self.results=[]
            def next_input(self):return self.actions.pop(0) if self.actions else None
            def mark_sent(self):self.sent+=1
            def finish_capture(self,error=None):self.results.append(error)
        qmp=QMP();control=Control();inputs=Inputs(qmp,allow_capture=True)
        for at,pins,main in [(1,'G1=0','1'),(3,'G13=0','3'),(7,'G13=1','1'),(9,'G1=1','0')]:
            row=inputs.tick(control,at)
            self.assertEqual(row['mcu_pins'],pins)
            self.assertEqual(qmp.values[-2:],[('mcu-pins',pins),('capture-gpio-input',main)])
        self.assertEqual(control.sent,1);self.assertEqual(len(control.actions),1)
        self.assertIsNone(inputs.tick(control,10));self.assertEqual(control.results,[])
        control.capture_completed_jobs=1
        self.assertIsNone(inputs.tick(control,10.5));self.assertEqual(control.results,[])
        control.capture_retired=True
        self.assertEqual(inputs.tick(control,11)['kind'],'capture-complete');self.assertEqual(control.results,[None])
        self.assertEqual(inputs.tick(control,12)['contact'],'23.6')
        inputs.release();control.actions=[('capture',None)]
        inputs.tick(control,14);inputs.release()
        self.assertEqual(qmp.values[-2:],[('mcu-pins','G1=1:G13=1'),('capture-gpio-input','0')])
        self.assertEqual(control.results[-1],'Capture inputs cancelled.')
        control.actions=[('capture',None)]
        inputs.tick(control,15)
        for at in (17,21,23):inputs.tick(control,at)
        self.assertEqual(inputs.tick(control,35)['kind'],'capture-timeout')
        self.assertIn('not confirmed',control.results[-1]);self.assertIsNone(inputs.capture)

    def test_wake_lease_requires_new_reset_then_readiness_and_releases_on_cancel(self):
        class QMP:
            def __init__(self):self.values=[]
            def command(self,name,**kw):self.values.append((kw['property'],kw['value']))
        class Control:
            def __init__(self):
                self.info=dict(sensor_frames=10,display_frames=20);self.actions=[('wake',None)];self.supply_resets=2;self.ready=False;self.powered_down=True;self.results=[];self.sent=0
            def next_input(self):return self.actions.pop(0) if self.actions else None
            def mark_sent(self):self.sent+=1
            def finish_wake(self,error=None):self.results.append(error)
        qmp=QMP();control=Control();inputs=Inputs(qmp,allow_wake=True)
        self.assertEqual(inputs.tick(control,1)['kind'],'wake-contact')
        self.assertEqual(qmp.values[-1],('mcu-pins','C5=0:G0=1'))
        self.assertIsNone(inputs.tick(control,1.25))
        self.assertEqual(inputs.tick(control,1.5)['kind'],'wake-release')
        self.assertEqual(qmp.values[-1],('mcu-pins','G0=0'))
        control.ready=True;control.powered_down=False
        self.assertIsNone(inputs.tick(control,2))
        control.supply_resets=3;control.ready=False
        self.assertIsNone(inputs.tick(control,3))
        control.ready=True
        self.assertIsNone(inputs.tick(control,3.5))
        control.info['sensor_frames']=11
        self.assertIsNone(inputs.tick(control,3.6))
        control.info['display_frames']=21
        self.assertEqual(inputs.tick(control,4)['kind'],'wake-complete')
        self.assertEqual(control.results,[None])
        control.actions=[('wake',None)];inputs.tick(control,5);inputs.release()
        self.assertEqual(qmp.values[-1],('mcu-pins','G0=0'))
        self.assertEqual(control.results[-1],'Wake inputs cancelled.')
        control.actions=[('wake',None)];inputs.tick(control,6);inputs.tick(control,6.5)
        self.assertEqual(inputs.tick(control,36)['kind'],'wake-timeout')
        self.assertIn('not confirmed',control.results[-1]);self.assertIsNone(inputs.wake)
        control.actions=[('wake',None)]
        with self.assertRaises(ValueError):Inputs(qmp).tick(control,40)
