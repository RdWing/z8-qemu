# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from z8_global1_boundary_input import Peer
class QMP:
 def __init__(self):self.now=0;self.inputs=[];self.reads=[]
 def command(self,command,**kw):
  if command=='qom-set':self.inputs.append((kw['property'],kw['value']));return {}
  name=kw['property'];self.reads.append(name)
  return json.dumps({'runtime-clock-state':dict(running=True,virtual_ns=self.now),
   'event1508-aux0-state':dict(enabled=True,mask=5),
   'event1508-aux1-state':dict(enabled=True,mask=2)}[name])
class Guest:
 def __init__(self,p):self.out=p;self.qmp=QMP();self.data={}
class Boundaries(unittest.TestCase):
 def test_declared_banks_virtual_time_and_no_catchup(self):
  with tempfile.TemporaryDirectory() as t:
   g=Guest(Path(t));p=Peer(g,33,auxiliary_masked=True,auxiliary1_masked=True,global0_bit26=True)
   p.tick();self.assertEqual(g.qmp.inputs,[('event1508-global1-input','128'),('event1508-aux0-input','1'),('event1508-aux1-input','2'),('event1508-global0-input','67108864')])
   g.qmp.now=32000000;p.tick();self.assertEqual(len(g.qmp.inputs),4)
   g.qmp.now=999000000;p.tick();self.assertEqual(len(g.qmp.inputs),8)
   self.assertEqual(p.record['total_deliveries'],2)
   self.assertEqual(p.record['auxiliary1_deliveries'],2)
   self.assertFalse(p.record['clock_stepped']);self.assertEqual(p.record['pixel_bytes'],0)
 def test_legacy_profile_does_not_query_or_drive_new_banks(self):
  with tempfile.TemporaryDirectory() as t:
   g=Guest(Path(t));p=Peer(g,33,auxiliary_masked=True);p.tick()
   self.assertEqual(len(g.qmp.inputs),2)
   self.assertNotIn('event1508-aux1-state',g.qmp.reads)
