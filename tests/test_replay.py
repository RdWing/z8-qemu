# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from replay import Replay

class ReplayTests(unittest.TestCase):
    def load(self, rows):
        path=Path(self.tmp.name)/'actions.json';path.write_text(json.dumps(rows));return Replay(path)
    def setUp(self):self.tmp=tempfile.TemporaryDirectory()
    def tearDown(self):self.tmp.cleanup()
    def test_readiness_and_virtual_time(self):
        r=self.load([dict(after=2,kind='mode',value='movie'),dict(after=5,kind='button',value='half')])
        self.assertIsNone(r.next_input())
        r.publish(None,dict(virtual_seconds=100),False);self.assertIsNone(r.next_input())
        r.publish(None,dict(virtual_seconds=110),True);self.assertIsNone(r.next_input())
        r.publish(None,dict(virtual_seconds=112),False);self.assertEqual(r.next_input(),('mode','movie'))
        self.assertIsNone(r.next_input())
        r.publish(None,dict(virtual_seconds=115),False);self.assertEqual(r.next_input(),('button',7))
        self.assertIsNone(r.next_input())
    def test_rejects_invalid_requests(self):
        for rows in [[],[dict(after=float('nan'),kind='mode',value='movie')],[dict(after=0,kind='button',value='unknown')],
                     [dict(after=2,kind='button',value='half'),dict(after=1,kind='button',value='menu')]]:
            with self.assertRaises(ValueError):self.load(rows)
