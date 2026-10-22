# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit tracing profiles preserve disabled defaults and reject ambiguous input."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import trace_plugin
import desktop_session


class TraceProfile(unittest.TestCase):
    def test_disabled_profile_and_validated_cli_roundtrip(self):
        parser=argparse.ArgumentParser();trace_plugin.arguments(parser)
        self.assertIsNone(trace_plugin.validate(parser.parse_args([])))
        with tempfile.TemporaryDirectory() as temp:
            plugin=Path(temp)/'lib trace $(literal).dylib';plugin.write_bytes(b'compiled fixture')
            config=dict(trace_plugin=str(plugin),trace_calls=[0x40160000,0x08000040],
                trace_watch=dict(lo=0x20000000,hi=0x20000010,pclo=0x08000000,pchi=0x08000100),
                trace_cpu=4,trace_limit=12,trace_per_site=2)
            profile=trace_plugin.configuration(config)
            self.assertEqual(trace_plugin.validate(parser.parse_args(trace_plugin.cli_args(profile))),profile)
            guest=argparse.Namespace(out=Path(temp)/'output',command=[],data={})
            trace_plugin.attach(guest,profile)
            self.assertEqual(guest.command[0],'-plugin')
            self.assertIn('calls=0x40160000:0x8000040',guest.command[1])
            self.assertIn('cpu=4',guest.command[1]);self.assertTrue(guest.data['trace_plugin']['observation_only_requested'])
            self.assertEqual(guest.data['trace_plugin']['clock'],'host_monotonic_us')
            base=dict(firmware=str(plugin),qemu=str(plugin),raw=str(plugin),output=str(guest.out))
            args=desktop_session.command(dict(base,**config))
            self.assertEqual(trace_plugin.validate(parser.parse_args(args[args.index('--trace-plugin'):])),profile)

    def test_rejects_missing_plugin_unbounded_and_ambiguous_profiles(self):
        with tempfile.TemporaryDirectory() as temp:
            plugin=Path(temp)/'plugin.dylib';plugin.touch()
            base=dict(trace_plugin=str(plugin),trace_calls=[0x40160000])
            invalid=[dict(trace_plugin='relative'),dict(trace_calls=[True]),dict(trace_calls=[-2]),
                dict(trace_calls=[0x40160001]),dict(trace_calls=[2]*33),dict(trace_calls=[2,2]),
                dict(trace_calls=[]),dict(trace_limit=0),dict(trace_limit=1000001),dict(trace_cpu=16),
                dict(trace_per_site=True),dict(trace_watch=dict(lo=2,hi=1,pclo=0,pchi=1)),
                dict(trace_watch=dict(lo=0,hi=1,pclo=0,pchi=1,extra=1)),
                dict(trace_app_log=True),dict(trace_app_log=0),dict(trace_app_log=-2),
                dict(trace_app_log=2),dict(trace_app_log=3),dict(trace_app_log=1<<64)]
            invalid.extend([dict(trace_access='read'),dict(trace_access='write'),
                dict(trace_access='both'),dict(trace_access=True)])
            for change in invalid:
                with self.subTest(change=change),self.assertRaises(ValueError):trace_plugin.configuration(dict(base,**change))
            with self.assertRaises(ValueError):trace_plugin.configuration(dict(trace_calls=[2]))
            parser=argparse.ArgumentParser();trace_plugin.arguments(parser)
            with self.assertRaises(ValueError):trace_plugin.validate(parser.parse_args(['--trace-watch','1:2:3']))

    def test_memory_access_selection_survives_cli_desktop_and_attach(self):
        parser=argparse.ArgumentParser();trace_plugin.arguments(parser)
        with tempfile.TemporaryDirectory() as temp:
            plugin=Path(temp)/'plugin.dylib';plugin.touch()
            base=dict(trace_plugin=str(plugin),trace_watch=dict(lo=1,hi=2,pclo=4,pchi=8))
            self.assertEqual(trace_plugin.configuration(base)['access'],'write')
            for access in ('read','write','both'):
                config=dict(base,trace_access=access);profile=trace_plugin.configuration(config)
                self.assertEqual(trace_plugin.validate(parser.parse_args(trace_plugin.cli_args(profile))),profile)
                guest=argparse.Namespace(out=Path(temp)/'output',command=[],data={})
                trace_plugin.attach(guest,profile)
                self.assertEqual(guest.data['trace_plugin']['access'],access)
                self.assertEqual('access='+access in guest.command[1],access!='write')
                args=desktop_session.command(dict(config,firmware=str(plugin),qemu=str(plugin),raw=str(plugin),output=str(guest.out)))
                self.assertEqual(trace_plugin.validate(parser.parse_args(args[args.index('--trace-plugin'):])),profile)
            for invalid in ('load',True,[],None):
                with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                    trace_plugin.configuration(dict(base,trace_access=invalid))

    def test_explicit_application_log_only_roundtrip_and_attach(self):
        parser=argparse.ArgumentParser();trace_plugin.arguments(parser)
        with tempfile.TemporaryDirectory() as temp:
            plugin=Path(temp)/'plugin.dylib';plugin.touch()
            profile=trace_plugin.configuration(dict(trace_plugin=str(plugin),trace_app_log=0x100))
            self.assertEqual(trace_plugin.validate(parser.parse_args(trace_plugin.cli_args(profile))),profile)
            self.assertEqual(profile['app_log'],0x100)
            self.assertEqual(profile['calls'],[])
            guest=argparse.Namespace(out=Path(temp)/'output',command=[],data={})
            trace_plugin.attach(guest,profile)
            self.assertIn('app_log=0x100',guest.command[1])
            self.assertEqual(guest.data['trace_plugin']['app_log'],0x100)


if __name__=='__main__':unittest.main()
