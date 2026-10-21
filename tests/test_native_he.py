# SPDX-License-Identifier: GPL-2.0-or-later
"""Native HE inputs stay explicit and snapshots cannot escape modeled RAM."""
from pathlib import Path
from types import SimpleNamespace
import json
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import native_he

class NativeHE(unittest.TestCase):
    def test_explicit_profile_and_snapshot_ownership(self):
        values={name:True for name in native_he.OPTIONS}
        values.update(card='card.raw',contact_replay='contacts.json',
                      experimental_shared221=True,experimental_boundary_inputs=True,
                      experimental_sensor_source_clock=True,experimental_yuv_channels=True,
                      experimental_movie_selector16=True)
        self.assertTrue(native_he.validate(SimpleNamespace(**values)))
        for name in values:
            with self.subTest(name=name),self.assertRaises(ValueError):
                native_he.validate(SimpleNamespace(**dict(values,**{name:False})))
        disabled=dict(values,**{name:False for name in native_he.OPTIONS})
        self.assertFalse(native_he.validate(SimpleNamespace(**disabled)))
        with tempfile.TemporaryDirectory() as temp:
            guest=SimpleNamespace(command=['qemu','-M','nikon-z8-full-lab'],data={},out=Path(temp))
            native_he.attach(guest,SimpleNamespace(**values))
            self.assertEqual((guest.out/'experimental-bank8-999.bin').read_bytes(),b'\x01')
            self.assertEqual((guest.out/'experimental-selector5.bin').read_bytes(),b'\x01')
            self.assertFalse(guest.data['experimental_native_he']['host_mcu_messages'])
            states={name:{} for name in native_he.STATES}
            states.update({'engine152c-he-still-state':dict(jobs=1,acks=1,pending=False),
                'engine152c-request-state':dict(output=0x800010000,capacity=64,width=8,height=4),
                'primary-d980-state':dict(submitted={'0x100':32},last_physical=0x800020000)})
            class QMP:
                def __init__(self):self.events=[]
                def command(self,command,**kwargs):
                    self.events.append(command)
                    return {'running':True} if command=='query-status' else json.dumps(states[kwargs['property']]) if command=='qom-get' else {}
                def hmp(self,command):self.events.append(command)
            guest.qmp=QMP();native_he.sample(guest)
            self.assertEqual(guest.data['he_snapshots']['pitch'],32)
            self.assertEqual(sum(x.startswith('pmemsave') for x in guest.qmp.events),2)
            self.assertEqual(guest.qmp.events[-1],'cont')
            states['engine152c-he-still-state'].update(jobs=2,acks=2)
            native_he.sample(guest)
            self.assertEqual(guest.data['he_capture_snapshots'][-1]['capture_index'],2)
            self.assertEqual(guest.data['he_capture_snapshots'][-1]['output'],'he-receiver-output-002.bin')
            self.assertEqual(guest.data['he_snapshots']['capture_index'],1)
            states['engine152c-he-still-state'].update(jobs=3,acks=3)
            states['primary-d980-state']['last_physical']=0x900000000-64
            guest.qmp.events=[]
            with self.assertRaises(ValueError):native_he.sample(guest)
            self.assertFalse(any(x.startswith('pmemsave') for x in guest.qmp.events))
