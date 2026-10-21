# SPDX-License-Identifier: GPL-2.0-or-later
"""The desktop/browser share readiness and playback capability admission."""
from pathlib import Path
import http.client
import json
import sys
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from control import Control, BUTTONS

class ControlAdmission(unittest.TestCase):
    def test_session_readiness_and_playback_are_separate(self):
        owner=Control(0)
        connection=http.client.HTTPConnection('127.0.0.1',owner.server.server_address[1],timeout=3)
        def post(key,token=None):
            connection.request('POST','/button/'+key,headers={'X-Control-Token':token or owner.token})
            reply=connection.getresponse();reply.read();return reply.status
        try:
            self.assertEqual(post('menu','old-session'),403)
            self.assertEqual(post('menu'),503)
            owner.ready=True;owner.last_publish=time.monotonic()
            self.assertEqual(post('play'),409)
            self.assertEqual(owner.queue.qsize(),0)
            self.assertEqual(post('menu'),202)
            self.assertEqual(owner.next_input(),('button',67))
            owner.playback=True
            self.assertEqual(post('play'),202)
            self.assertEqual(owner.next_input(),('button',68))
            owner.native_mcu=True;owner.allowed_buttons=set()
            self.assertEqual(post('menu'),409)
            owner.allowed_buttons={'play'};owner.playback=False
            self.assertEqual(post('play'),409)
            owner.playback=True;self.assertEqual(post('play'),202)
            self.assertEqual(owner.next_input(),('button',68))
            owner.allowed_buttons={'menu','ok'}
            self.assertEqual(post('half'),409)
            self.assertEqual(post('menu'),202)
            self.assertEqual(owner.next_input(),('button',67))
            owner.native_mcu=False;owner.allowed_buttons=set(BUTTONS)
            owner.last_publish-=6
            self.assertEqual(post('play'),503)
        finally:connection.close();owner.close()

    def test_native_mode_capability_and_readiness_are_independent(self):
        owner=Control(0,native_mcu=True,native_buttons={'menu','half'},native_modes=True)
        connection=http.client.HTTPConnection('127.0.0.1',owner.server.server_address[1],timeout=3)
        def mode():
            connection.request('POST','/mode/movie',headers={'X-Control-Token':owner.token})
            reply=connection.getresponse();reply.read();return reply.status
        try:
            self.assertTrue(owner.status()['mode_available']);self.assertEqual(mode(),503)
            owner.ready=True;owner.last_publish=time.monotonic()
            self.assertEqual(mode(),202);self.assertEqual(owner.next_input(),('mode','movie'))
            owner.native_modes=False;self.assertEqual(mode(),409)
            self.assertEqual(owner.queue.qsize(),0)
        finally:connection.close();owner.close()

    def test_terminal_power_cancels_queue_and_keeps_last_frame(self):
        import tempfile
        from pathlib import Path
        owner=Control(0,native_mcu=True,native_buttons={'half','menu'},native_modes=True)
        connection=http.client.HTTPConnection('127.0.0.1',owner.server.server_address[1],timeout=3)
        try:
            with tempfile.TemporaryDirectory() as temp:
                frame=Path(temp)/'frame.ppm';frame.write_bytes(b'P6\n1 1\n255\n\x11\x22\x33')
                row={'raw':{'frames':20},'lcd':{'frames':30},'virtual_seconds':20}
                owner.publish(frame,row,ready=True);pixels=owner.png
                owner.queue.put_nowait(('button',7))
                owner.publish(frame,dict(row,powered_down=True),ready=True)
                self.assertEqual(owner.png,pixels);self.assertFalse(owner.status()['ready'])
                self.assertTrue(owner.status()['powered_down']);self.assertEqual(owner.status()['cancelled_inputs'],1)
                self.assertEqual(owner.queue.qsize(),0);self.assertIsNone(owner.next_input())
                owner.publish(frame,row,ready=True);self.assertFalse(owner.status()['ready'])
                connection.request('POST','/mode/movie',headers={'X-Control-Token':owner.token})
                reply=connection.getresponse();reply.read();self.assertEqual(reply.status,503)
                connection.request('POST','/stop',headers={'X-Control-Token':owner.token})
                reply=connection.getresponse();reply.read();self.assertEqual(reply.status,200)
        finally:connection.close();owner.close()
