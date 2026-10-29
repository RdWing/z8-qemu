# SPDX-License-Identifier: GPL-2.0-or-later
"""Publication guards check removed history and exclude unlisted runtime files."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from audit_privacy import audit, inspect
from package_runtime import copy_runtime


class Privacy(unittest.TestCase):
    def test_categories_report_locations_without_disclosing_matching_values(self):
        samples = {
            'personal filesystem path': ('/'+'/'.join(['Users', 'example-person', 'input'])).encode(),
            'private workspace reference': ('nikon-z-'+'research-priv').encode(),
            'private key': ('-----BEGIN '+'PRIVATE KEY-----').encode(),
            'credential token': ('ghp_'+'A'*36).encode(),
            'credential-bearing URL': ('https://'+'user:pass'+'@example.invalid').encode(),
            'literal credential assignment': ('api_key="'+'a'*30+'"').encode(),
            'binary payload': b'header\0tail',
        }
        for expected, data in samples.items():
            with self.subTest(expected=expected):
                findings = inspect('example.py', b'first\n'+data)
                self.assertIn(expected, [x[0] for x in findings])
                self.assertNotIn(data.decode(errors='replace'), repr(findings))
        self.assertIn(('private input/output filename', 0), inspect('removed.NEF', b''))
        for name in ('host.wav','capture.s32le','capture.s24le'):
            self.assertIn(('private input/output filename',0),inspect(name,b''))
        self.assertEqual(inspect('example.json', b'{"sha256":"' + b'a'*64 + b'"}'), [])

    def test_removed_content_and_historical_payload_names_are_still_checked(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            def git(*args):
                return subprocess.check_output(['git','-c','user.name=Example','-c',
                    'user.email=example@example.invalid',*args],cwd=root,stderr=subprocess.DEVNULL)
            git('init','-q')
            (root/'input.py').write_text('path='+repr('/'+'/'.join(['Users','example-person','input']))+'\n')
            (root/'payload.bin').write_text('same plain text\n')
            git('add','.');git('commit','-qm','Initial fixture')
            (root/'input.py').write_text('value=1\n')
            git('mv','payload.bin','source.txt');git('add','.');git('commit','-qm','Remove private fixture')
            self.assertEqual(audit(root)[2], [])
            checked, objects, findings = audit(root, history=True)
            self.assertEqual(checked, 2);self.assertGreater(objects, 2)
            self.assertIn('personal filesystem path', [x[1] for x in findings])
            self.assertTrue(any('payload.bin' in x[0] for x in findings))

    def test_runtime_is_allowlisted_hashed_and_rejects_symlinks_and_payloads(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'tools').mkdir()
            source=root/'tools/public.py';source.write_text('value=1\n')
            (root/'tools/local-notes.json').write_text('{"note":"unlisted local input"}')
            manifest={'files':{'tools/public.py':hashlib.sha256(source.read_bytes()).hexdigest()}}
            def save(): (root/'source-manifest.json').write_text(json.dumps(manifest))
            save();destination=root/'bundle/runtime/tools'
            self.assertEqual(copy_runtime(root,destination),1)
            self.assertEqual([p.name for p in destination.iterdir()],['public.py'])
            self.assertEqual((destination/'public.py').read_bytes(),source.read_bytes())
            source.write_text('value=2\n')
            with self.assertRaisesRegex(ValueError,'fingerprint'):copy_runtime(root,root/'mismatch')
            self.assertFalse((root/'mismatch').exists())
            target=root/'outside.py';target.write_text('value=1\n');source.unlink();source.symlink_to(target)
            with self.assertRaisesRegex(ValueError,'symlink'):copy_runtime(root,root/'symlink')
            manifest['files']={'tools/private.bin':'a'*64};save()
            with self.assertRaisesRegex(ValueError,'path'):copy_runtime(root,root/'payload')
            manifest['files']={'tools/../outside.py':'a'*64};save()
            with self.assertRaisesRegex(ValueError,'path'):copy_runtime(root,root/'escape')


if __name__=='__main__':unittest.main()
