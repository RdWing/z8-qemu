# SPDX-License-Identifier: GPL-2.0-or-later
"""Terminal firmware park is distinct from boot, ordinary WFI and MCU activity."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from native_power import powered_down

class NativePower(unittest.TestCase):
    def test_exact_terminal_state_and_negative_controls(self):
        clock={'cpus':[{'index':0,'pc':0x082012F8,'halted':True},
                       {'index':1,'pc':0x08201354,'halted':True},
                       {'index':2,'pc':0x082013B0,'halted':True},
                       {'index':3,'pc':0x082013D4,'halted':True},
                       {'index':4,'pc':0x08051D24,'halted':False}]}
        original=copy.deepcopy(clock)
        self.assertTrue(powered_down(clock,0));self.assertEqual(clock,original)
        self.assertFalse(powered_down(clock,6));self.assertFalse(powered_down({},0))
        for index in range(3):
            candidate=copy.deepcopy(clock);candidate['cpus'][index]['pc']=0x40189A7C
            self.assertFalse(powered_down(candidate,0)) # Ordinary scheduler WFI.
            candidate=copy.deepcopy(clock);candidate['cpus'][index]['halted']=False
            self.assertFalse(powered_down(candidate,0))
            candidate=copy.deepcopy(clock);del candidate['cpus'][index]['pc']
            self.assertFalse(powered_down(candidate,0)) # Older diagnostic schema.
