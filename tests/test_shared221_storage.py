"""Synthetic metadata controls for the imported read-only storage helpers."""
from pathlib import Path
import struct
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from isobmff_raw_index import raw_packets
from virtual_exfat_window import window


def box(kind,body):return struct.pack('>I4s',8+len(body),kind)+body

def table(rows):return bytes(4)+struct.pack('>I',len(rows))+b''.join(struct.pack('>'+'I'*len(r),*r) for r in rows)

class Metadata(unittest.TestCase):
    def test_large_offsets_without_reading_payload(self):
        boundary=(1<<32)+512;positions=[(1<<32)+32,(1<<32)+64,(1<<32)+96]
        stbl=box(b'stsz',bytes(4)+struct.pack('>II',8,3))
        stbl+=box(b'co64',bytes(4)+struct.pack('>I3Q',3,*positions))
        stbl+=box(b'stsc',table([(1,1,1)]))+box(b'stts',table([(3,1001)]))
        moov=box(b'moov',box(b'trak',box(b'mdia',box(b'hdlr',bytes(8)+b'vide')+box(b'minf',box(b'stbl',stbl)))))
        class Reader:
            size=boundary+len(moov)
            calls=[]
            def read_at(self,offset,n):
                self.calls.append((offset,n))
                if offset==0:return struct.pack('>I4sQ',1,b'mdat',boundary)[:n]
                if offset>=boundary:return moov[offset-boundary:offset-boundary+n]
                raise AssertionError('Attempted to read picture payload')
        r=Reader();rows=raw_packets(r)
        self.assertEqual([int(v['pos']) for v in rows],positions)
        self.assertEqual([v['pts'] for v in rows],[0,1001,2002])
        self.assertLess(sum(n for _,n in r.calls),1024)

    def test_bounded_mbr_volume_window(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'card.img';data=bytearray(8192)
            data[510:512]=b'\x55\xaa';data[450]=7
            struct.pack_into('<II',data,454,1,8);data[515:523]=b'EXFAT   '
            p.write_bytes(data);self.assertEqual(window(p),(512,4096))
            struct.pack_into('<I',data,458,10000);p.write_bytes(data)
            with self.assertRaises(ValueError):window(p)

if __name__=='__main__':unittest.main()
