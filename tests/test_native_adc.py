# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit ADC profiles validate before process launch or replay admission."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import native_adc
import desktop_session
from native_contact_replay import ContactReplay


class NativeADC(unittest.TestCase):
    def test_numeric_bounds_atomic_batch_shape_and_duplicates(self):
        self.assertEqual(native_adc.validate('1.0=0:2.1=2048:3.18=4095'),'1.0=0:2.1=2048:3.18=4095')
        for value in ('','1.0=0:', '0.0=1', '4.0=1','1.19=1','1.0=4096','1.0=-1','1.0=1:01.00=2',True,'1.0=0,2.0=0','1.0=0x10','1.0= 1'):
            with self.subTest(value=value),self.assertRaises(ValueError):native_adc.validate(value)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.touch()
            config=dict(firmware=str(source),qemu=str(source),raw=str(source),output=str(root/'new'),mcu_adc_inputs='1.1=2048')
            with self.assertRaises(ValueError):desktop_session.command(config)
            config['mcu']=str(source);args=desktop_session.command(config)
            self.assertEqual(args[args.index('--mcu-adc-inputs')+1],'1.1=2048')
            replay=root/'replay.json';replay.write_text(json.dumps([dict(at=1,property='mcu-adc-inputs',value='1.1=2048')]))
            reader=ContactReplay(replay)
            class QMP:
                def command(self,*args,**kwargs):self.value=kwargs['value']
            qmp=QMP();self.assertEqual(len(reader.dispatch(qmp,1)),1);self.assertEqual(qmp.value,'1.1=2048')
            replay.write_text(json.dumps([dict(at=1,property='mcu-adc-inputs',value='1.1=4096')]))
            with self.assertRaises(ValueError):ContactReplay(replay)


if __name__=='__main__':unittest.main()
