# SPDX-License-Identifier: GPL-2.0-or-later
"""Desktop launch validation and private process-group shutdown controls."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('desktop_session',ROOT/'tools/desktop_session.py')
desktop=importlib.util.module_from_spec(spec);spec.loader.exec_module(desktop)

class DesktopSession(unittest.TestCase):
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
                            dict(experimental_sensor_source_clock=True),dict(experimental_boundary_inputs=True)]:
                with self.subTest(changes=changes),self.assertRaises(ValueError):desktop.command(dict(config,**changes))
            args=desktop.command(dict(config,card=str(source),experimental_playback=True))
            self.assertIn('--experimental-playback',args)
            args=desktop.command(dict(config,mcu=str(source)))
            self.assertIn('--mcu',args);self.assertTrue(args[2].endswith('run_native.py'))
            with self.assertRaises(ValueError):desktop.command(dict(config,mcu=str(source),card=str(source)))
            args=desktop.command(dict(config,mcu=str(source),native_controls=True))
            self.assertIn('--native-controls',args)
            with self.assertRaises(ValueError):desktop.command(dict(config,mcu=str(source),native_controls='yes'))
            movie=dict(experimental_shared221=True,experimental_boundary_inputs=True,
                       experimental_yuv_channels=True,experimental_movie_selector16=True,
                       experimental_sensor_source_clock=True)
            args=desktop.command(dict(config,**movie))
            for flag in movie:self.assertIn('--'+flag.replace('_','-'),args)
            with self.assertRaises(ValueError):desktop.command(dict(config,mcu=str(source),**movie))


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
