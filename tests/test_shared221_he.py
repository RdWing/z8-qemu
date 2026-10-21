#!/usr/bin/env python3
"""Exercise the actual functional HE C ABI with synthetic packed14 input.

No R3D container, SDK, camera firmware or reference image is used.
"""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'qemu'

class FunctionalHE(unittest.TestCase):
    def test_roundtrip_tail_geometry_and_rejected_packets(self):
        main = r'''
#include "nikon-he-runtime.h"
#include <algorithm>
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <vector>
int main() {
 for (unsigned w : {64u, 66u, 128u, 130u}) {
  unsigned h=72, pitch=((w*14+7)/8+31)&~31u;
  std::vector<uint8_t> packed(pitch*h,0), encoded(32768), again(encoded.size());
  std::vector<uint16_t> source(w*h), decoded(w*h,65535);
  for(unsigned y=0;y<h;y++)for(unsigned x=0;x<w;x++) {
   unsigned value=1024+(x*71+y*43)%12000;
   source[y*w+x]=value;
   size_t at=size_t(y)*pitch+x*14/8; unsigned shift=(x*14)&7;
   uint32_t bits=value<<shift;
   packed[at]|=bits;packed[at+1]|=bits>>8;
   if(shift>2)packed[at+2]|=bits>>16;
  }
  assert(wl_he_encode14(packed.data(),packed.size(),w,h,pitch,encoded.data(),encoded.size()));
  assert(wl_he_encode14(packed.data(),packed.size(),w,h,pitch,again.data(),again.size()));
  assert(encoded==again);
  assert(wl_he_decode14(encoded.data(),encoded.size(),w,h,decoded.data(),decoded.size()));
  unsigned max_error=0;uint64_t total=0;
  for(size_t i=0;i<source.size();i++){
   unsigned e=unsigned(std::abs(int(source[i])-int(decoded[i])));
   max_error=std::max(max_error,e);total+=e;assert(decoded[i]<=16383);
  }
  // A bounded functional roundtrip, never a Nikon encoder equivalence test.
  assert(max_error<256);
  std::printf("HE %ux%u maximum_error=%u mean_error=%.6f\n",w,h,max_error,double(total)/source.size());
  for(unsigned i=0;i<8;i++)assert(wl_he_decode14(encoded.data(),encoded.size(),w,h,decoded.data(),decoded.size()));
  for(size_t n : {size_t(0),size_t(255),encoded.size()-1})
   assert(!wl_he_decode14(encoded.data(),n,w,h,decoded.data(),decoded.size()));
  assert(!wl_he_decode14(encoded.data(),encoded.size(),w+2,h,decoded.data(),decoded.size()));
  assert(!wl_he_decode14(encoded.data(),encoded.size(),w,h,decoded.data(),decoded.size()-1));
  auto corrupt=encoded;corrupt[0]=0;
  assert(!wl_he_decode14(corrupt.data(),corrupt.size(),w,h,decoded.data(),decoded.size()));
  corrupt=encoded;corrupt.back()=0;
  assert(!wl_he_decode14(corrupt.data(),corrupt.size(),w,h,decoded.data(),decoded.size()));
  assert(!wl_he_encode14(packed.data(),packed.size()-1,w,h,pitch,encoded.data(),encoded.size()));
 }
 assert(!wl_he_decode14(nullptr,256,64,8,nullptr,512));
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as temp:
            d=Path(temp);(d/'main.cpp').write_text(main)
            command=['c++','-std=c++17','-O1','-g','-fsanitize=address,undefined',
                     '-I'+str(SOURCE), str(d/'main.cpp'),str(SOURCE/'nikon-he-runtime.cpp')]
            command += [str(p) for p in sorted((SOURCE/'nikon-he-public').glob('*.cpp'))]
            subprocess.run(command+['-o',str(d/'test')],check=True,timeout=120)
            subprocess.run([str(d/'test')],check=True,timeout=120)

if __name__=='__main__': unittest.main()
