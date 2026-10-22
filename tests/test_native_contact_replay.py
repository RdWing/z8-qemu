# SPDX-License-Identifier: GPL-2.0-or-later
"""Contact replay admits external pins only and uses virtual-time ordering."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from native_contact_replay import ContactReplay

class Contacts(unittest.TestCase):
    def test_ordering_and_external_only_bounds(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'contacts.json'
            rows=[dict(at=1,property='mcu-pins',value='G1=1:G13=1'),dict(at=2,property='mcu-contacts',value='23.6=0'),dict(at=3,property='capture-gpio-input',value='3')]
            path.write_text(json.dumps(rows));replay=ContactReplay(path)
            class QMP:
                def __init__(self):self.sent=[]
                def command(self,*args,**kwargs):self.sent.append((args,kwargs))
            qmp=QMP();self.assertEqual(replay.dispatch(qmp,.9),[])
            self.assertEqual(len(replay.dispatch(qmp,1)),1);self.assertEqual(len(replay.dispatch(qmp,1)),0)
            self.assertEqual(len(replay.dispatch(qmp,2)),1);self.assertEqual(qmp.sent[-1][1]['value'],'23.6=0')
            self.assertEqual(len(replay.dispatch(qmp,3)),1);self.assertEqual(qmp.sent[-1][1]['value'],'3')
            for change in [dict(at=-.1),dict(at=float('nan')),dict(at=True),dict(property='cpu-pc'),
                           dict(value='G16=1'),dict(value='G1=1:'),dict(value='23.24=0'),dict(value='24.6=0'),
                           dict(property='capture-gpio-input',value='1:3'),dict(property='capture-gpio-input',value='4')]:
                candidate=dict(rows[0],**change);path.write_text(json.dumps([candidate]))
                with self.subTest(change=change),self.assertRaises(ValueError):ContactReplay(path)
