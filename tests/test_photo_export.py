# SPDX-License-Identifier: GPL-2.0-or-later
"""Stopped-card export preserves real bytes, lock ownership and atomic outcomes."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from desktop_photo_export import card_read_lease, export_photos, _flock_type, publish_directory


def file_set(name, cluster, length, *, directory=False, valid=None, contiguous=True):
    import struct
    value = bytearray(96)
    value[0] = 0x85; value[1] = 2
    struct.pack_into('<H', value, 4, 0x10 if directory else 0x20)
    value[32] = 0xc0; value[33] = 2 if contiguous else 0; value[35] = len(name)
    struct.pack_into('<Q', value, 40, length if valid is None else valid)
    struct.pack_into('<I', value, 52, cluster); struct.pack_into('<Q', value, 56, length)
    value[64] = 0xc1; encoded = name.encode('utf-16le'); value[66:66+len(encoded)] = encoded
    checksum = 0
    for offset, byte in enumerate(value):
        if offset not in (2, 3): checksum = (((checksum >> 1) | ((checksum & 1) << 15)) + byte) & 0xffff
    struct.pack_into('<H', value, 2, checksum)
    return value


def fixture(root, *, broken=False, partial=False, empty=False):
    import struct
    card = root/'card.raw'; data = bytearray(66*512)
    data[3:11] = b'EXFAT   '; data[108] = 9; data[109] = 0
    struct.pack_into('<IIIII', data, 80, 1, 1, 2, 64, 2)
    struct.pack_into('<I', data, 512+2*4, 0xffffffff)
    data[1024:1120] = file_set('DCIM', 3, 512, directory=True)
    data[1536:1632] = file_set('100NCZ_8', 4, 512, directory=True)
    expected = {'DSC_0001.NEF': b'II*\0actual virtual NEF payload', 'DSC_0002.JPG': b'\xff\xd8actual virtual JPEG payload\xff\xd9'}
    if not empty:
        first, second = expected.values()
        data[2048:2144] = file_set('DSC_0001.NEF', 5, len(first), valid=1 if partial else None)
        data[2144:2240] = file_set('DSC_0002.JPG', 6, 1024 if broken else len(second), contiguous=not broken)
        data[2560:2560+len(first)] = first; data[3072:3072+len(second)] = second
        if broken: struct.pack_into('<I', data, 512+6*4, 6)
    card.write_bytes(data)
    session = root/'session'; session.mkdir()
    (session/'result.json').write_text(json.dumps(dict(owned_qemu_stopped=True, persistent_card=dict(path=str(card)))))
    return card, session, expected


class PhotoExport(unittest.TestCase):
    def test_cancellation_reaps_worker_and_removes_only_private_staging(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); card, session, _=fixture(root); original=card.read_bytes()
            harness=root/'slow_export.py'
            harness.write_text("import sys,time\nfrom pathlib import Path\nsys.path.insert(0,"+repr(str(ROOT/'tools'))+")\nimport desktop_photo_export as export\ndef slow(card,staging,connection):\n staging.mkdir();(staging.parent/'ready').touch();time.sleep(60)\nif __name__=='__main__':\n export._copy_worker=slow;export.main()\n")
            process=subprocess.Popen([sys.executable,str(harness),'--card',str(card),'--session',str(session),'--output',str(root/'photos')],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                deadline=time.monotonic()+5
                while not list(root.glob('.z8-photo-export-*/ready')) and time.monotonic()<deadline: time.sleep(.01)
                self.assertTrue(list(root.glob('.z8-photo-export-*/ready')))
                process.terminate(); out, error=process.communicate(timeout=5)
                self.assertNotEqual(process.returncode,0)
                self.assertIn('cancelled',json.loads(out)['message'])
                self.assertFalse((root/'photos').exists())
                self.assertFalse(list(root.glob('.z8-photo-export-*')))
                self.assertEqual(card.read_bytes(),original)
            finally:
                if process.poll() is None: process.kill(); process.communicate()

    def test_exact_photos_without_private_receipts_or_overwrites(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); card, session, expected=fixture(root)
            original=card.read_bytes(); destination=root/'photos $(literal)'
            result=export_photos(card, session, destination)
            self.assertEqual(result['count'], 2)
            self.assertEqual(result['bytes'], sum(map(len, expected.values())))
            for name, data in expected.items():
                self.assertEqual((destination/'DCIM/100NCZ_8'/name).read_bytes(), data)
            self.assertEqual(len(list(destination.rglob('*.*'))), 2)
            self.assertEqual(card.read_bytes(), original)
            with self.assertRaises(ValueError): export_photos(card, session, destination)
            self.assertEqual((destination/'DCIM/100NCZ_8/DSC_0001.NEF').read_bytes(), expected['DSC_0001.NEF'])

    def test_failure_is_atomic_and_stopped_receipt_is_required(self):
        for variant in ('broken', 'partial', 'empty'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as temp:
                root=Path(temp); card, session, _=fixture(root, **{variant:True}); before=card.read_bytes()
                with self.assertRaises(ValueError): export_photos(card, session, root/'photos')
                self.assertFalse((root/'photos').exists())
                self.assertFalse(list(root.glob('.z8-photo-export-*')))
                self.assertEqual(card.read_bytes(), before)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); card, session, _=fixture(root)
            for receipt in (dict(owned_qemu_stopped=False, persistent_card=dict(path=str(card))),
                            dict(owned_qemu_stopped=True, persistent_card=dict(path=str(root/'other.raw')))):
                (session/'result.json').write_text(json.dumps(receipt))
                with self.assertRaises(ValueError): export_photos(card, session, root/'photos')
            source=root/'staging'; source.mkdir(); destination=root/'existing'; destination.mkdir()
            with self.assertRaises(ValueError): publish_directory(source, destination)
            self.assertTrue(source.is_dir()); self.assertTrue(destination.is_dir())

    def test_qemu_writer_locks_and_native_flock_layout(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); card, _, _=fixture(root)
            code="import fcntl,sys;f=open(sys.argv[1],'rb');fcntl.lockf(f,fcntl.LOCK_SH,1,101);print('ready',flush=True);sys.stdin.read()"
            writer=subprocess.Popen([sys.executable,'-c',code,str(card)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
            try:
                self.assertEqual(writer.stdout.readline().strip(),'ready')
                with self.assertRaisesRegex(ValueError,'in use'):
                    with card_read_lease(card): self.fail('Writer must exclude export')
            finally: writer.communicate('')
            with card_read_lease(card):
                # An external QEMU-compatible writer sees our denied-sharing byte.
                code="import sys,fcntl;sys.path.insert(0,sys.argv[2]);from desktop_photo_export import _flock_type;f=open(sys.argv[1],'rb');T=_flock_type();q=T(kind=fcntl.F_WRLCK,whence=0,start=201,length=1);r=T.from_buffer_copy(fcntl.fcntl(f,fcntl.F_GETLK,bytes(q)));assert r.kind!=fcntl.F_UNLCK"
                subprocess.run([sys.executable,'-c',code,str(card),str(ROOT/'tools')],check=True)
            source=root/'layout.c'; binary=root/'layout'
            source.write_text('#include <fcntl.h>\n#include <stddef.h>\n#include <stdio.h>\nint main(void){printf("%zu %zu %zu %zu %zu %zu\\n",sizeof(struct flock),offsetof(struct flock,l_type),offsetof(struct flock,l_whence),offsetof(struct flock,l_start),offsetof(struct flock,l_len),offsetof(struct flock,l_pid));}\n')
            subprocess.run([os.environ.get('CC','cc'),str(source),'-o',str(binary)],check=True)
            native=list(map(int,subprocess.check_output([str(binary)],text=True).split()))
            structure=_flock_type()
            self.assertEqual(native,[ctypes.sizeof(structure),*[getattr(structure,k).offset for k in ('kind','whence','start','length','pid')]])


if __name__ == '__main__': unittest.main()
