# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Firmware-free executable checks and owned cancellation/timeout cleanup."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import qemu_preflight


@unittest.skipIf(os.name == 'nt', 'POSIX executable check lifecycle')
class QemuPreflight(unittest.TestCase):
    def executable(self, root, code):
        path = root/'qemu $(literal)'
        path.write_text('#!'+sys.executable+'\n'+code+'\n')
        path.chmod(0o700)
        return path

    def test_only_version_is_requested_without_shell_interpretation(self):
        with tempfile.TemporaryDirectory(prefix='z8 preflight ') as temp:
            root = Path(temp); marker = root/'arguments.json'
            binary = self.executable(root, 'import json,sys,pathlib;pathlib.Path('+repr(str(marker))+').write_text(json.dumps(sys.argv[1:]))')
            result = qemu_preflight.check(binary)
            self.assertEqual(json.loads(marker.read_text()), ['--version'])
            self.assertEqual(result['process_status'], 0)
            self.assertIn('firmware and machine startup were not tested', result['qualification'])
            self.assertLess(result['elapsed_seconds'], 3)

    def test_invalid_path_timeout_and_preexisting_cancellation_do_not_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); marker = root/'started'
            binary = self.executable(root, 'import pathlib;pathlib.Path('+repr(str(marker))+').touch()')
            for timeout in (0, -1, True, float('nan'), float('inf'), 61):
                with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                    qemu_preflight.check(binary, timeout=timeout)
            for path in ('relative', root, root/'missing'):
                with self.subTest(path=path), self.assertRaises(ValueError):
                    qemu_preflight.check(path)
            with self.assertRaises(InterruptedError):
                qemu_preflight.check(binary, cancelled=lambda: True)
            self.assertFalse(marker.exists())

    def test_nonzero_exit_is_distinct_from_guest_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            binary = self.executable(Path(temp), 'raise SystemExit(7)')
            with self.assertRaisesRegex(RuntimeError, 'QEMU --version exited with status 7; no firmware session'):
                qemu_preflight.check(binary)

    def test_timeout_reaps_unresponsive_check_and_descendant(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); marker = root/'pids.json'
            binary = self.executable(root,
                'import json,os,pathlib,signal,time\n'
                'signal.signal(signal.SIGTERM,signal.SIG_IGN)\n'
                'child=os.fork()\n'
                'if child==0: time.sleep(60); os._exit(0)\n'
                'pathlib.Path('+repr(str(marker))+').write_text(json.dumps([os.getpid(),child]))\n'
                'time.sleep(60)')
            started = time.monotonic()
            with self.assertRaisesRegex(TimeoutError, 'QEMU --version did not finish'):
                # Leave interpreter startup time before testing process-group cleanup.
                qemu_preflight.check(binary, timeout=2)
            self.assertLess(time.monotonic()-started, 5)
            self.assertTrue(marker.exists())
            parent, child = json.loads(marker.read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(parent, 0)
            # A killed orphan can briefly remain a zombie until the OS reaps it.
            deadline = time.monotonic()+1
            while True:
                try:
                    os.kill(child, 0)
                except ProcessLookupError:
                    break
                if sys.platform.startswith('linux'):
                    try:
                        if Path(f'/proc/{child}/stat').read_text().split(') ', 1)[1].startswith('Z '):
                            break
                    except FileNotFoundError:
                        break
                self.assertLess(time.monotonic(), deadline, 'healthcheck descendant still running')
                time.sleep(.01)

    def test_cancellation_reaps_check(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); marker = root/'pid'
            binary = self.executable(root, 'import os,pathlib,time;pathlib.Path('+repr(str(marker))+').write_text(str(os.getpid()));time.sleep(60)')
            with self.assertRaisesRegex(InterruptedError, 'executable check cancelled'):
                qemu_preflight.check(binary, cancelled=marker.exists)
            with self.assertRaises(ProcessLookupError):
                os.kill(int(marker.read_text()), 0)

    def test_cli_reports_version_check_scope_and_signal_cancellation(self):
        completed = subprocess.run([sys.executable, str(ROOT/'tools/qemu_preflight.py'), '--qemu', sys.executable],
                                   capture_output=True, text=True, timeout=3)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['process_status'], 0)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); marker = root/'pid'
            binary = self.executable(root, 'import os,pathlib,time;pathlib.Path('+repr(str(marker))+').write_text(str(os.getpid()));time.sleep(60)')
            process = subprocess.Popen([sys.executable, str(ROOT/'tools/qemu_preflight.py'), '--qemu', str(binary)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                deadline = time.monotonic()+3
                while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue(marker.exists())
                process.terminate(); stdout, stderr = process.communicate(timeout=3)
                self.assertEqual(process.returncode, 130, stderr)
                self.assertEqual(stdout, '')
                self.assertIn('no firmware session was started', stderr)
                with self.assertRaises(ProcessLookupError):
                    os.kill(int(marker.read_text()), 0)
            finally:
                if process.poll() is None:
                    process.kill(); process.communicate()


if __name__ == '__main__':
    unittest.main()
