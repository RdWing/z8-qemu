# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Audit copies must preserve bytes across sparse holes and partial reads."""
import json
from pathlib import Path
import struct
import random
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import virtual_recording_card as card
from copy_card import copy_card


class SparseCardAudit(unittest.TestCase):
    def test_audit_partition_is_byte_exact(self):
        with tempfile.TemporaryDirectory(prefix='z8-card-extents-') as directory:
            source = Path(directory)/'card.raw'
            offset, size = 1024*1024, 16*1024*1024
            mbr = bytearray(512)
            struct.pack_into('<B3sB3sII', mbr, 446, 0, bytes(3), 7,
                             bytes(3), offset//512, (size-offset)//512)
            mbr[510:] = b'\x55\xaa'
            with source.open('wb') as stream:
                stream.truncate(size)
                stream.write(mbr)
                for start, length in ((512, 0x364000-512),
                                      (0x380000, 0xf0000),
                                      (0x480000, 0xa0000),
                                      (9*1024*1024+37, 4811)):
                    stream.seek(start)
                    stream.write(random.Random(start).randbytes(length))
            before = source.read_bytes()
            # Filesystem interpretation is independent of this copy test.
            with patch.object(card, 'check_volume', return_value=
                              subprocess.CompletedProcess([], 0, '', '')):
                result = card.audit(source)
            self.assertEqual(Path(result['derived_volume']).read_bytes(), before[offset:])
            self.assertEqual(source.read_bytes(), before)
            self.assertTrue(result['source_unchanged'])
            self.assertFalse(result['codec_verified'])
            self.assertEqual(json.loads(source.with_suffix('.audit.json').read_text())['fsck_exit'], 0)
            clone = Path(directory)/'clone.raw'
            copy_card(source, clone)
            self.assertEqual(clone.read_bytes(), before)

    def test_buffered_extent_scan_is_rejected(self):
        with tempfile.TemporaryFile('w+b') as stream:
            stream.write(b'header')
            stream.seek(0)
            stream.read(1)
            with self.assertRaisesRegex(ValueError, 'unbuffered'):
                list(card.extents(stream, 6))


if __name__ == '__main__':
    unittest.main()
