#!/usr/bin/env python3
"""Run patched JPEG/provenance/reset controls on synthetic input.

Apply the patch series first. No camera firmware or guest is needed. Optional
Z8_LV_BASELINE_JPEG_HEADER adds a byte comparison with the pre-0053 codec.
"""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get('Z8_LV_QEMU_SOURCE', ROOT))
FIXTURES = ROOT/'tests'


def compile_and_run(name, directory, *, codec=False, baseline=None):
    directory.mkdir(parents=True)
    executable = directory/'test'
    command = shlex.split(os.environ.get('CC', 'cc')) + [
        '-std=c11', '-Wall', '-Wextra', '-Werror',
        '-fsanitize=address,undefined', str(FIXTURES/name), '-o', str(executable)]
    if codec:
        flags = subprocess.run(['pkg-config', '--cflags', '--libs', 'libjpeg'],
                               check=True, capture_output=True, text=True).stdout
        command += shlex.split(flags)
        command += [f'-DJPEG_HEADER="{baseline}"'] if baseline else ['-DTEST_NV12']
    subprocess.run(command, check=True, timeout=60)
    subprocess.run([str(executable)] + ([str(directory)] if codec else []),
                   check=True, timeout=30)


class LiveViewJPEG(unittest.TestCase):
    def test_completed_buffer_generations(self):
        with tempfile.TemporaryDirectory() as temp:
            compile_and_run('test_liveview_buffers.c', Path(temp)/'buffers')

    def test_unfinished_reset_and_pending_result_guards(self):
        with tempfile.TemporaryDirectory() as temp:
            compile_and_run('test_liveview_reset.c', Path(temp)/'reset')

    def test_actual_nv12_decode_and_bounds(self):
        with tempfile.TemporaryDirectory() as temp:
            compile_and_run('test_liveview_jpeg.c', Path(temp)/'codec', codec=True)

    @unittest.skipUnless(os.environ.get('Z8_LV_BASELINE_JPEG_HEADER'),
                         'Set Z8_LV_BASELINE_JPEG_HEADER for the legacy byte comparison')
    def test_unchanged_nv16_streams(self):
        baseline = Path(os.environ['Z8_LV_BASELINE_JPEG_HEADER']).resolve(strict=True)
        with tempfile.TemporaryDirectory() as temp:
            current, previous = Path(temp)/'current', Path(temp)/'previous'
            compile_and_run('test_liveview_jpeg.c', current, codec=True)
            compile_and_run('test_liveview_jpeg.c', previous, codec=True, baseline=baseline)
            for scale in range(3):
                name = f'nv16-scale{scale}.jpg'
                self.assertEqual((current/name).read_bytes(), (previous/name).read_bytes(), name)


if __name__ == '__main__':
    unittest.main()
