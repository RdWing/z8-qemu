# SPDX-License-Identifier: GPL-2.0-or-later
"""Real child startup distinguishes cancellation from process failure and reaps both."""
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from guest_transport import Transport


class PendingGuest(Transport):
    def __exit__(self, kind, error, traceback):
        self.caught = error
        if self.proc.poll() is None:
            self.proc.terminate()
        self.proc.wait(timeout=3)


class GuestStartup(unittest.TestCase):
    def test_cancel_during_socket_wait_reaps_the_owned_process(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); guest=PendingGuest(); guest.runtime=root; guest.log_path=root/'stderr.log'; guest.data={}
            marker=root/'child-ready'
            guest.command=[sys.executable,'-c',"from pathlib import Path;import time;Path("+repr(str(marker))+").touch();time.sleep(60)"]
            guest.startup_cancelled=marker.exists
            at=time.monotonic()
            with self.assertRaisesRegex(InterruptedError,'cancelled'): guest.__enter__()
            self.assertLess(time.monotonic()-at,3)
            self.assertIsNotNone(guest.proc.poll())
            self.assertIn('cancelled',guest.data['qemu_startup_failure']['message'])

    def test_early_process_exit_has_its_actual_status(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); guest=PendingGuest(); guest.runtime=root; guest.log_path=root/'stderr.log'; guest.data={}
            guest.command=[sys.executable,'-c','raise SystemExit(7)']
            with self.assertRaisesRegex(RuntimeError,'status 7'): guest.__enter__()
            self.assertEqual(guest.data['qemu_startup_failure']['process_status'],7)
            self.assertEqual(guest.proc.returncode,7)

    def test_uart_and_diagnostics_are_retained_separately_on_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); guest=PendingGuest(); guest.runtime=root; guest.log_path=root/'stderr.log'; guest.data={}
            guest.command=[sys.executable,'-c',"import os;os.write(1,b'UART\\x00\\xff\\r\\n');os.write(2,b'diagnostic\\n');raise SystemExit(4)"]
            with self.assertRaisesRegex(RuntimeError,'status 4'):guest.__enter__()
            self.assertEqual((root/'uart-tx.log').read_bytes(),b'UART\x00\xff\r\n')
            self.assertEqual(guest.log_path.read_bytes(),b'diagnostic\n')
            self.assertFalse(guest.data['uart_tx']['receive_supported'])
            # A stale output directory may never overwrite an earlier UART log.
            with self.assertRaises(FileExistsError):guest.__enter__()
            self.assertEqual((root/'uart-tx.log').read_bytes(),b'UART\x00\xff\r\n')
