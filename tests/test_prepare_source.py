# Copyright (C) 2026 RdWing: Z8 adaptation.
"""Source overlay upgrades preserve independently edited QEMU files."""
from pathlib import Path
import importlib.util
import json
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('prepare_z8',ROOT/'qemu/prepare_source.py')
prepare=importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)

class SourceOverlay(unittest.TestCase):
    def seed(self,root):
        files={'VERSION':'11.1.1\n','hw/arm/Kconfig':'config ARM_TEST\n    bool\n',
               'hw/arm/meson.build':"hw_common_arch += {'arm': arm_common_ss}\n",
               'configs/devices/aarch64-softmmu/default.mak':'CONFIG_ARM_TEST=y\n',
               'hw/pci-host/designware.c':prepare.DMA_OLD,
               'accel/tcg/tcg-accel-ops.c':prepare.TCG_OLD}
        for name,data in files.items():
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(data)
        for name in json.loads((ROOT/'qemu/qemu-core/sources.json').read_text()):
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_bytes((ROOT/'qemu/qemu-core'/name).read_bytes())
        return files

    def test_install_repeat_and_divergent_upgrade(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);original=self.seed(root)
            self.assertFalse(prepare.prepare(root,check=True)['source_changed'])
            self.assertFalse((root/'.z8-qemu-overlay.json').exists())
            receipt=prepare.prepare(root)
            self.assertEqual(receipt,prepare.prepare(root))
            self.assertIn('hw/arm/nikon-he-public/nikon_he_decode.cpp',receipt)
            meson=(root/'hw/arm/meson.build').read_text()
            self.assertEqual(meson.count('# BEGIN Z8 OVERLAY'),1)
            self.assertIn("cpp_std=c++17",meson)
            self.assertIn("dependency('x264')",meson)
            for name,data in original.items():
                if name!='VERSION':self.assertEqual((root/'.z8-qemu-backup'/name).read_text(),data)
            target=root/'hw/arm/nikon-z8-lab.c'
            target.write_text(target.read_text()+'\n/* independently edited */\n')
            before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with self.assertRaisesRegex(ValueError,'divergent'):
                prepare.prepare(root)
            self.assertEqual(before,{p:p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_version_rejection_does_not_install(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);self.seed(root);(root/'VERSION').write_text('11.1.2\n')
            with self.assertRaisesRegex(ValueError,'11.1.1'):prepare.prepare(root)
            self.assertFalse((root/'hw/arm/nikon-z8-lab.c').exists())
