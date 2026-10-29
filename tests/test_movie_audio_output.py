# SPDX-License-Identifier: GPL-2.0-or-later
"""Movie host output remains explicit, fresh and separate from source media."""
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import movie_playback

class MovieAudioOutput(unittest.TestCase):
    def guest(self):
        return SimpleNamespace(command=['qemu','-M','nikon-z8-full-lab'],data={})

    def test_auto_and_explicit_silent_profile(self):
        g=self.guest();movie_playback.attach(g)
        self.assertIn('serial5-audio-output=auto',g.command[2])
        self.assertIn('serial5-playback-ram-aperture-fixture=on',g.command[2])
        self.assertIn('backend-program-epoch-model=on',g.command[2])
        self.assertNotIn('-audiodev',g.command)
        g=self.guest();movie_playback.attach(g,'none')
        self.assertNotIn('serial5-audio-output=',g.command[2])
        self.assertEqual(g.data['experimental_movie_playback']['audio_output'],'none')

    def test_fresh_wav_and_rejected_destinations(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);dest=root/'host output.wav'
            g=self.guest();movie_playback.attach(g,str(dest))
            self.assertIn('path='+str(dest),g.command[g.command.index('-audiodev')+1])
            self.assertFalse(dest.exists())
            dest.write_bytes(b'keep')
            bad=[str(dest),str(root/'bad,output.wav'),str(root/'bad.log'),str(root/'missing'/'x.wav'),False,'']
            for value in bad:
                with self.subTest(value=value),self.assertRaises(ValueError):movie_playback.validate_audio_output(value)
            self.assertEqual(dest.read_bytes(),b'keep')
            alias=root/'link.wav';alias.symlink_to(root/'absent')
            with self.assertRaises(ValueError):movie_playback.validate_audio_output(str(alias))

if __name__=='__main__':unittest.main()
