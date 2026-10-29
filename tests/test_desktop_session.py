# SPDX-License-Identifier: GPL-2.0-or-later
"""Desktop launch validation and private process-group shutdown controls."""
import importlib.util
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
spec=importlib.util.spec_from_file_location('desktop_session',ROOT/'tools/desktop_session.py')
desktop=importlib.util.module_from_spec(spec);spec.loader.exec_module(desktop)

class DesktopSession(unittest.TestCase):
    def test_preflight_failure_creates_no_session_or_launcher_log(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.touch()
            output=root/'sessions/new';config=root/'config.json'
            config.write_text(json.dumps(dict(firmware=str(source),raw=str(source),qemu=str(source),output=str(output))))
            with mock.patch.object(sys,'argv',['desktop_session.py','--config',str(config)]), \
                 mock.patch.object(desktop.signal,'signal'), \
                 mock.patch.object(desktop.qemu_preflight,'check',side_effect=TimeoutError('QEMU --version timed out')) as check:
                with self.assertRaisesRegex(TimeoutError,'QEMU --version'):
                    desktop.main()
            check.assert_called_once()
            self.assertFalse(output.parent.exists())
            self.assertFalse(output.with_name(output.name+'.desktop.log').exists())

    def test_invalid_configuration_is_rejected_before_executing_qemu(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.touch();config=root/'config.json'
            config.write_text(json.dumps(dict(firmware=str(source),raw=str(source),qemu=str(source),output=str(root/'new'),unknown=True)))
            with mock.patch.object(sys,'argv',['desktop_session.py','--config',str(config)]), \
                 mock.patch.object(desktop.qemu_preflight,'check') as check:
                with self.assertRaisesRegex(ValueError,'Unknown desktop'):
                    desktop.main()
            check.assert_not_called()

    def test_check_only_preserves_launcher_validation_after_preflight(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.touch();config=root/'config.json'
            config.write_text(json.dumps(dict(firmware=str(source),raw=str(source),qemu=str(source),output=str(root/'new'))))
            order=[]
            with mock.patch.object(sys,'argv',['desktop_session.py','--config',str(config),'--check-only']), \
                 mock.patch.object(desktop.signal,'signal'), \
                 mock.patch.object(desktop.qemu_preflight,'check',side_effect=lambda *a,**k: order.append('preflight')), \
                 mock.patch.object(desktop.subprocess,'run',side_effect=lambda args,**k: order.append(args[-1])):
                desktop.main()
            self.assertEqual(order,['preflight','--check-only'])
            self.assertFalse((root/'new').exists())

    def test_cancellation_after_preflight_does_not_launch_session(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.touch();config=root/'config.json'
            config.write_text(json.dumps(dict(firmware=str(source),raw=str(source),qemu=str(source),output=str(root/'sessions/new'))))
            handlers={};events=io.StringIO()
            with mock.patch.object(sys,'argv',['desktop_session.py','--config',str(config)]), \
                 mock.patch.object(desktop.signal,'signal',side_effect=lambda sig,handler: handlers.update({sig:handler})), \
                 mock.patch.object(desktop.qemu_preflight,'check',side_effect=lambda *a,**k: handlers[signal.SIGTERM](None,None)), \
                 mock.patch.object(desktop.subprocess,'Popen') as launch, contextlib.redirect_stdout(events):
                desktop.main()
            launch.assert_not_called()
            self.assertEqual(json.loads(events.getvalue()),dict(event='stopped'))
            self.assertFalse((root/'sessions').exists())

    @unittest.skipIf(os.name=='nt','POSIX private healthcheck lifecycle')
    def test_stop_during_real_preflight_reaps_qemu_without_reading_firmware(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source';source.write_bytes(b'not firmware')
            qemu=root/'qemu';pid=root/'qemu.pid'
            qemu.write_text('#!'+sys.executable+'\nimport os,pathlib,time\npathlib.Path('+repr(str(pid))+').write_text(str(os.getpid()))\ntime.sleep(60)\n')
            qemu.chmod(0o700)
            config=root/'config.json';output=root/'sessions/new'
            config.write_text(json.dumps(dict(firmware=str(source),raw=str(source),qemu=str(qemu),output=str(output))))
            process=subprocess.Popen([sys.executable,str(ROOT/'tools/desktop_session.py'),'--config',str(config)],
                                     stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                deadline=time.monotonic()+3
                while not pid.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(pid.exists())
                process.terminate();stdout,stderr=process.communicate(timeout=3)
                self.assertEqual(process.returncode,0,stderr)
                self.assertEqual(json.loads(stdout),dict(event='stopped'))
                self.assertFalse(output.parent.exists())
                with self.assertRaises(ProcessLookupError):os.kill(int(pid.read_text()),0)
            finally:
                if process.poll() is None:process.kill();process.communicate()

    @unittest.skipUnless(sys.platform=='darwin', 'Native bounded diagnostics reader')
    def test_native_log_snapshots_are_bounded_and_reject_nonregular_inputs(self):
        source=(ROOT/'desktop/Z8.swift').read_text()
        function=source[source.index('func readDiagnosticLog('):source.index('final class Diagnostics:')]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);log=root/'log';link=root/'link';fifo=root/'fifo'
            log.write_bytes(b'old'*100000+b'UART\x00\xff\r\n');link.symlink_to(log);os.mkfifo(fifo)
            swift=root/'main.swift';binary=root/'reader'
            swift.write_text('import Foundation\nimport Darwin\n'+function+
                'for path in CommandLine.arguments.dropFirst() { print(readDiagnosticLog(URL(fileURLWithPath:path),limit:8)) }\n')
            subprocess.run(['xcrun','swiftc','-module-cache-path',str(root/'cache'),str(swift),'-o',str(binary)],check=True,capture_output=True)
            def read(path):return subprocess.run([str(binary),str(path)],check=True,capture_output=True,timeout=3).stdout.decode()
            self.assertEqual(read(log),'UART\\x00\ufffd\r\n\n')
            self.assertIn('Log unavailable',read(link))
            self.assertIn('regular file',read(fifo))
            self.assertIn('Log unavailable',read(root/'missing'))
            log.write_bytes(b'new\n');self.assertEqual(read(log),'new\n\n')
            log.write_bytes(b'');self.assertEqual(read(log),'No output yet.\n')

    def test_explicit_paths_flags_and_rejections(self):
        with tempfile.TemporaryDirectory(prefix='z8 desktop ') as temp:
            root=Path(temp);source=root/'input $(literal).bi';source.touch()
            config=dict(firmware=str(source),qemu=str(source),raw=str(source),output=str(root/'new'),seconds=30)
            args=desktop.command(config)
            self.assertEqual(args[args.index('--firmware')+1],str(source))
            self.assertEqual(args[-2:],['--port','0'])
            for changes in [dict(output=str(source)),dict(seconds=True),dict(seconds=3601),
                            dict(raw='relative'),dict(extra='unowned'),dict(experimental_playback=True),
                            dict(experimental_shared221='yes'),dict(native_controls=True),
                            dict(experimental_sensor_source_clock=True),dict(experimental_boundary_inputs=True),
                            dict(experimental_main_supply_pin="C1")]:
                with self.subTest(changes=changes),self.assertRaises(ValueError):desktop.command(dict(config,**changes))
            args=desktop.command(dict(config,card=str(source),experimental_playback=True))
            self.assertIn('--experimental-playback',args)
            args=desktop.command(dict(config,mcu=str(source)))
            self.assertIn('--mcu',args);self.assertTrue(args[2].endswith('run_native.py'))
            self.assertNotIn('--experimental-main-supply-pin',args)
            args=desktop.command(dict(config,mcu=str(source),experimental_main_supply_pin='C1'))
            self.assertEqual(args[args.index('--experimental-main-supply-pin')+1],'C1')
            for pin in ('C16',True,None,'C1,other=on'):
                with self.subTest(pin=pin),self.assertRaises(ValueError):
                    desktop.command(dict(config,mcu=str(source),experimental_main_supply_pin=pin))
            args=desktop.command(dict(config,mcu=str(source),card=str(source)))
            self.assertIn('--card',args)
            with self.assertRaises(ValueError):desktop.command(dict(config,mcu=str(source),card=str(source),experimental_playback=True))
            args=desktop.command(dict(config,mcu=str(source),native_controls=True))
            self.assertIn('--native-controls',args)
            with self.assertRaises(ValueError):desktop.command(dict(config,mcu=str(source),native_controls='yes'))
            movie=dict(experimental_shared221=True,experimental_boundary_inputs=True,
                       experimental_yuv_channels=True,experimental_movie_selector16=True,
                       experimental_sensor_source_clock=True)
            args=desktop.command(dict(config,**movie))
            for flag in movie:self.assertIn('--'+flag.replace('_','-'),args)
            args=desktop.command(dict(config,mcu=str(source),native_controls=True,**movie))
            self.assertIn('--native-controls',args)
            self.assertIn('--experimental-movie-selector16',args)
            args=desktop.command(dict(config,mcu=str(source),card=str(source),experimental_playback=True,**movie))
            self.assertIn('--experimental-playback',args)
            with self.assertRaises(ValueError):desktop.command(dict(config,experimental_native_he=True))
            for changes in [dict(native_controls=False),dict(card=None),dict(experimental_yuv_channels=False)]:
                candidate=dict(config,mcu=str(source),card=str(source),native_controls=True,experimental_native_he=True,**movie)
                candidate.update(changes)
                with self.subTest(changes=changes),self.assertRaises(ValueError):desktop.command(candidate)
            args=desktop.command(dict(config,mcu=str(source),card=str(source),native_controls=True,experimental_native_he=True,**movie))
            for flag in ('he-still','preparation-profile','capture-selector5','timed-single'):
                self.assertIn('--experimental-'+flag,args)
            self.assertNotIn('--experimental-he-live-preview',args)
            capture=dict(config,mcu=str(source),card=str(source),native_controls=True,experimental_native_he=True,**movie)
            args=desktop.command(dict(capture,experimental_he_live_preview=True))
            self.assertIn('--experimental-he-live-preview',args)
            for changes in [dict(experimental_native_he=False),dict(experimental_he_live_preview='yes')]:
                candidate=dict(capture,experimental_he_live_preview=True);candidate.update(changes)
                with self.subTest(changes=changes),self.assertRaises(ValueError):desktop.command(candidate)

    def test_explicit_application_log_hook_forwards_to_both_launchers(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'input';source.touch()
            config=dict(firmware=str(source),qemu=str(source),raw=str(source),output=str(root/'new'),
                        trace_plugin=str(source),trace_app_log=0x100)
            for native in (False,True):
                with self.subTest(native=native):
                    args=desktop.command(dict(config,**({'mcu':str(source)} if native else {})))
                    self.assertEqual(args[args.index('--trace-app-log')+1],'0x100')
                    self.assertNotIn('--trace-call',args)


    @unittest.skipUnless(sys.platform=='darwin', 'Native macOS Process environment')
    def test_native_python_and_descendants_leave_runtime_immutable(self):
        # Compile the production configuration function, then import a module
        # in real parent/child interpreters. A missing environment flag would
        # create __pycache__ inside the signed runtime.
        source=(ROOT/'desktop/Z8.swift').read_text()
        function=source[source.index('    func configurePython('):source.index('    func launch(')]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); runtime=root/'runtime';runtime.mkdir()
            (runtime/'module.py').write_text('value=1\n')
            code="import module,os,subprocess,sys;assert os.environ['Z8_RUNTIME_SENTINEL']=='retained';subprocess.run([sys.executable,'-c','import module'],check=True)"
            swift=root/'main.swift';binary=root/'check-runtime'
            swift.write_text('import Foundation\nfinal class Runtime {\n'+function+'}\n'+
                'let process=Process();Runtime().configurePython(process)\n'+
                'process.executableURL=URL(fileURLWithPath:'+json.dumps(sys.executable)+')\n'+
                'process.arguments=["-c",'+json.dumps(code)+']\n'+
                'process.currentDirectoryURL=URL(fileURLWithPath:'+json.dumps(str(runtime))+')\n'+
                'try process.run();process.waitUntilExit();precondition(process.terminationStatus==0)\n')
            subprocess.run(['xcrun','swiftc','-module-cache-path',str(root/'cache'),str(swift),'-o',str(binary)],check=True,capture_output=True)
            environment=os.environ.copy();environment.pop('PYTHONDONTWRITEBYTECODE',None)
            environment.pop('PYTHONPYCACHEPREFIX',None);environment['Z8_RUNTIME_SENTINEL']='retained'
            subprocess.run([str(binary)],env=environment,check=True,capture_output=True)
            self.assertFalse((runtime/'__pycache__').exists())

    @unittest.skipIf(os.name=='nt','POSIX private process-group lifecycle')
    def test_unresponsive_owned_group_is_reaped(self):
        with tempfile.TemporaryDirectory() as temp:
            marker=Path(temp)/'ready'
            code='import signal,time,pathlib;signal.signal(signal.SIGTERM,signal.SIG_IGN);pathlib.Path('+repr(str(marker))+').touch();time.sleep(60)'
            child=subprocess.Popen([sys.executable,'-c',code],start_new_session=True)
            try:
                deadline=time.monotonic()+3
                while not marker.exists() and time.monotonic()<deadline:time.sleep(.01)
                self.assertTrue(marker.exists())
                desktop.stop_child(child,grace=.1)
                self.assertEqual(child.returncode,-signal.SIGKILL)
            finally:
                if child.poll() is None:os.killpg(child.pid,signal.SIGKILL);child.wait()

if __name__=='__main__':unittest.main()
