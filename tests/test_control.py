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
            owner.allowed_buttons={'menu','ok'}
            self.assertEqual(post('half'),409)
            self.assertEqual(post('menu'),202)
            self.assertEqual(owner.next_input(),('button',67))
            owner.native_mcu=False;owner.allowed_buttons=set(BUTTONS)
            owner.last_publish-=6
            self.assertEqual(post('play'),503)
        finally:connection.close();owner.close()
