# SPDX-License-Identifier: GPL-2.0-or-later
"""Recording preparation remains an explicit complete-profile ROM input."""
import argparse
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import movie_inputs

class MovieProfile(unittest.TestCase):
    def test_record_selector_dependencies_and_declared_input(self):
        parser=argparse.ArgumentParser();parser.add_argument('--experimental-shared221',action='store_true')
        movie_inputs.arguments(parser)
        flags=['--experimental-'+name for name in ['shared221','boundary-inputs','sensor-source-clock',
               'yuv-channels','movie-selector16','movie-selector10']]
        args=parser.parse_args(flags);movie_inputs.validate(args)
        for missing in flags[:-1]:
            with self.subTest(missing=missing),self.assertRaises(ValueError):
                movie_inputs.validate(parser.parse_args([f for f in flags if f!=missing]))
        with tempfile.TemporaryDirectory() as temp:
            guest=SimpleNamespace(out=Path(temp),command=['qemu','-M','nikon-z8-full-lab'],data={})
            movie_inputs.attach(guest,args)
            self.assertEqual((guest.out/'experimental-selector10.bin').read_bytes(),b'\x01')
            self.assertIn('addr=0x47f5af4a',guest.command[-1])
            self.assertFalse(guest.data['experimental_movie_selector10']['factory_calibration'])
            self.assertFalse(any('capture-gpio' in x or 'mcu-contacts' in x for x in guest.command))
