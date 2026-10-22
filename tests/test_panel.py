# SPDX-License-Identifier: GPL-2.0-or-later
"""Panel pixels preserve model shift order, display gating and session isolation."""
import http.client
from pathlib import Path
import struct
import sys
import unittest
import zlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import panel
from control import Control


def scan(image):
    payload=b'';at=8
    while at<len(image):
        size=struct.unpack_from('>I',image,at)[0];tag=image[at+4:at+8]
        if tag==b'IDAT':payload+=image[at+8:at+8+size]
        at+=12+size
    return zlib.decompress(payload)


class Panel(unittest.TestCase):
    def test_pixel_order_corners_and_blank_display(self):
        bits=bytearray([255]*3024);bits[0]=0x7f;bits[-1]=0xfe
        raw=scan(panel.png(bits.hex(),True));self.assertEqual(len(raw),145*168)
        self.assertEqual(raw[1:10],bytes([0]+[255]*8))
        self.assertEqual(raw[-2:],bytes([255,0]))
        self.assertTrue(all(raw[y*145]==0 for y in range(168)))
        blank=scan(panel.png(bits.hex(),False))
        self.assertTrue(all(blank[y*145+1:(y+1)*145]==bytes([255]*144) for y in range(168)))
        for value,state in (('00',True),('z'*6048,True),(' '*6048,True),('ff'*3024,1)):
            with self.assertRaises(ValueError):panel.png(value,state)

    def test_native_http_snapshot_versions_and_unconfigured_session(self):
        owner=Control(0,native_mcu=True);connection=http.client.HTTPConnection('127.0.0.1',owner.server.server_address[1],timeout=3)
        def fetch():
            connection.request('GET','/panel.png');reply=connection.getresponse();return reply.status,reply.read()
        try:
            self.assertEqual(fetch()[0],404);self.assertFalse(owner.status()['panel_available'])
            metadata=dict(enabled=True,width=144,height=168,display_on=True,lines=1,packets=2)
            owner.publish_panel('ff'*3024,metadata);first=fetch()
            self.assertEqual(first[0],200);self.assertEqual(first[1],panel.png('ff'*3024,True))
            self.assertEqual(owner.status()['panel_version'],1)
            metadata['lines']=2;owner.publish_panel('ff'*3024,metadata)
            self.assertEqual(owner.status()['panel_version'],1);self.assertEqual(owner.status()['panel_lines'],2)
            owner.publish_panel('00'*3024,metadata);self.assertEqual(owner.status()['panel_version'],2)
            metadata['display_on']=False;owner.publish_panel('00'*3024,metadata)
            self.assertEqual(owner.status()['panel_version'],3)
            with self.assertRaises(ValueError):owner.publish_panel('ff'*3024,dict(metadata,width=145))
            owner.native_mcu=False
            self.assertEqual(fetch()[0],404);self.assertFalse(owner.status()['panel_available'])
            with self.assertRaises(ValueError):owner.publish_panel('ff'*3024,metadata)
        finally:connection.close();owner.close()


if __name__=='__main__':unittest.main()
