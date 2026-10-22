# SPDX-License-Identifier: GPL-2.0-or-later
"""Admission and ownership of shared Movie/card inputs across controller modes."""
from pathlib import Path
import json
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import movie_inputs
import virtual_card

class GuestInputs(unittest.TestCase):
    def test_card_media_admission_and_native_gpio_owner(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'virtual $(literal) card.raw';path.write_bytes(bytes(1024))
            with self.assertRaises(ValueError):virtual_card.validate(path)
            media=bytearray(1024);media[510:512]=b'\x55\xaa';struct.pack_into('<I',media,454,1)
            path.write_bytes(media)
            with self.assertRaises(ValueError):virtual_card.validate(path)
            media[515:523]=b'EXFAT   ';path.write_bytes(media)
            self.assertEqual(virtual_card.validate(path),path.resolve())
            comma=path.with_name('comma,card.raw');comma.write_bytes(media)
            with self.assertRaises(ValueError):virtual_card.validate(comma)
            for native in (False,True):
                guest=SimpleNamespace(command=['qemu','-M','nikon-z8-full-lab'],data={})
                virtual_card.attach(guest,path,playback=True,native_mcu=native)
                properties=dict(item.split('=',1) for item in guest.command[2].split(',')[1:])
                self.assertEqual(properties['ccomp-gpio-model'],'off' if native else 'on')
                self.assertEqual(properties['z8-jpeg-decode'],'on')
                self.assertEqual(guest.command[guest.command.index('-drive')+1],f'file={path},if=none,id=card,format=raw,file.locking=on')
                self.assertTrue(guest.data['persistent_card']['guest_writable'])
                self.assertEqual(guest.data['persistent_card']['file_locking'],'on')
                self.assertEqual(path.read_bytes(),media) # Attachment changes no media bytes.

    def test_movie_inputs_are_explicit_and_keep_code_unchanged(self):
        args=SimpleNamespace(experimental_shared221=False,experimental_boundary_inputs=True,experimental_sensor_source_clock=True,
            experimental_yuv_channels=True,experimental_movie_selector16=True)
        with self.assertRaises(ValueError):movie_inputs.validate(args)
        args.experimental_shared221=True;movie_inputs.validate(args)
        self.assertTrue(movie_inputs.native_modes_enabled(args))
        args.experimental_movie_selector16=False;self.assertFalse(movie_inputs.native_modes_enabled(args));args.experimental_movie_selector16=True
        with tempfile.TemporaryDirectory() as temp:
            guest=SimpleNamespace(command=['qemu','-M','nikon-z8-full-lab'],data={},out=Path(temp))
            movie_inputs.attach(guest,args)
            self.assertIn('z8-sensor-source-clock=on',guest.command[2])
            self.assertIn('yuvcmp-channel-ready-model=on',guest.command[2])
            self.assertEqual((guest.out/'experimental-selector16.bin').read_bytes(),b'\x01')
            self.assertFalse(guest.data['experimental_movie_selector16']['factory_calibration'])
            self.assertIn('addr=0x47f5af50',guest.command[-1])
            self.assertEqual(guest.command.count('-device'),1)

if __name__=='__main__':unittest.main()
