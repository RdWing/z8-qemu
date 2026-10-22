# SPDX-License-Identifier: GPL-2.0-or-later
"""Diagnostic exports preserve exact known logs and publish only complete ZIPs."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
import desktop_log_export as logs


class DiagnosticExport(unittest.TestCase):
    def setup_session(self, root):
        session = root/'session'; session.mkdir()
        (session/'result.json').write_text(json.dumps(dict(owned_qemu_stopped=True)))
        return session, root/'diagnostics.zip'

    def test_exact_known_logs_manifest_private_mode_and_no_extra_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);session,dest=self.setup_session(root)
            contents={'uart-tx.log':b'original\x00\xff\r\n','stderr.log':b'', 'plugin-trace.log':b'{"event":"summary"}\n',
                      'ex-usart6-tx.log':b'F'}
            for name,data in contents.items():(session/name).write_bytes(data)
            (root/'session.desktop.log').write_bytes(b'launcher\n')
            contents['launcher.log']=b'launcher\n'
            for name in ('firmware.bi','card.raw','capture.NEF','secret.txt'):(session/name).write_bytes(b'excluded')
            (session/'nested').mkdir();(session/'nested'/'stderr.log').write_bytes(b'excluded')
            result=logs.export_logs(session,dest)
            self.assertEqual(result['count'],5)
            self.assertEqual(dest.stat().st_mode & 0o777,0o600)
            with zipfile.ZipFile(dest) as archive:
                self.assertEqual(set(archive.namelist()),set(contents)|{'manifest.json'})
                manifest=json.loads(archive.read('manifest.json'))
                self.assertNotIn(str(root),archive.read('manifest.json').decode())
                for row in manifest['files']:
                    self.assertEqual(archive.read(row['name']),contents[row['name']])
                    self.assertEqual(row['sha256'],hashlib.sha256(contents[row['name']]).hexdigest())
                self.assertIn('ex-usart1-tx.log',manifest['missing'])
            self.assertEqual((session/'uart-tx.log').read_bytes(),contents['uart-tx.log'])

    def test_rejects_running_missing_empty_and_nonregular_sessions(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);session,dest=self.setup_session(root)
            with self.assertRaisesRegex(ValueError,'No diagnostic'):logs.export_logs(session,dest)
            (session/'stderr.log').write_bytes(b'log')
            (session/'result.json').write_text('{"owned_qemu_stopped":false}')
            with self.assertRaisesRegex(ValueError,'Stop the session'):logs.export_logs(session,dest)
            (session/'result.json').unlink()
            with self.assertRaises(FileNotFoundError):logs.export_logs(session,dest)
            (session/'result.json').symlink_to(root/'receipt');(root/'receipt').write_text('{"owned_qemu_stopped":true}')
            with self.assertRaises(OSError):logs.export_logs(session,dest)
            (session/'result.json').unlink();(session/'result.json').write_text('{"owned_qemu_stopped":true}')
            (session/'stderr.log').unlink();os.mkfifo(session/'stderr.log')
            with self.assertRaisesRegex(ValueError,'regular file'):logs.export_logs(session,dest)
            (session/'stderr.log').unlink();(session/'stderr.log').symlink_to(root/'receipt')
            with self.assertRaises(OSError):logs.export_logs(session,dest)
            alias=root/'alias';alias.symlink_to(session,target_is_directory=True)
            with self.assertRaises(OSError):logs.export_logs(alias,dest)
            self.assertFalse(dest.exists())

    def test_limits_existing_destinations_and_destination_race_preserve_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);session,dest=self.setup_session(root)
            (session/'stderr.log').write_bytes(b'12345')
            with patch.object(logs,'MAX_TOTAL_BYTES',4),self.assertRaisesRegex(ValueError,'512 MiB'):logs.export_logs(session,dest)
            dest.write_bytes(b'keep')
            with self.assertRaises(ValueError):logs.export_logs(session,dest)
            self.assertEqual(dest.read_bytes(),b'keep');dest.unlink()
            with self.assertRaises(ValueError):logs.export_logs(session,session/'nested.zip')
            original=logs.os.link
            def race(source,target,**kwargs):
                Path(target).write_bytes(b'raced');return original(source,target,**kwargs)
            with patch.object(logs.os,'link',race),self.assertRaises(FileExistsError):logs.export_logs(session,dest)
            self.assertEqual(dest.read_bytes(),b'raced')
            self.assertEqual(list(root.glob('.z8-log-export-*')),[])

    def test_changed_open_input_aborts_without_partial_publication(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);session,dest=self.setup_session(root);source=session/'stderr.log';source.write_bytes(b'12345')
            original=logs.open_regular
            def changed(directory,name):
                stream,info=original(directory,name)
                if name=='stderr.log':source.write_bytes(b'changed')
                return stream,info
            with patch.object(logs,'open_regular',changed),self.assertRaisesRegex(ValueError,'changed'):logs.export_logs(session,dest)
            self.assertFalse(dest.exists());self.assertEqual(list(root.glob('.z8-log-export-*')),[])

    def test_cli_cancellation_cleans_staging_without_publishing(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);session,dest=self.setup_session(root)
            with (session/'stderr.log').open('wb') as source:source.truncate(256*1024**2)
            child=subprocess.Popen([sys.executable,logs.__file__,'--session',str(session),'--output',str(dest)],stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                deadline=time.monotonic()+5
                while not list(root.glob('.z8-log-export-*')):
                    if child.poll() is not None or time.monotonic()>deadline:self.fail('Export did not begin staging')
                    time.sleep(.005)
                child.terminate();stdout,stderr=child.communicate(timeout=5)
                self.assertNotEqual(child.returncode,0);self.assertIn('cancelled',json.loads(stdout)['message'])
                self.assertFalse(dest.exists());self.assertEqual(list(root.glob('.z8-log-export-*')),[])
            finally:
                if child.poll() is None:child.kill();child.wait()


if __name__=='__main__':unittest.main()
