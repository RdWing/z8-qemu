# SPDX-License-Identifier: GPL-2.0-or-later
"""Exercise the real workbench mode API used by browser and native menu actions."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]

class WorkbenchModes(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node.js required for workbench boundary checks')
    def test_native_menu_uses_guarded_selector_queue(self):
        subprocess.run([shutil.which('node'), str(ROOT/'tests/fixtures/control-mode.cjs'),
                        str(ROOT/'tools/control.html')], check=True, capture_output=True, text=True)
