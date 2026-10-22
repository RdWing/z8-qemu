# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
import unittest
from source_helpers import ROOT,function
from test_shared221 import check
class Color8(unittest.TestCase):
 def test_output_tables_required_and_applied(self):
  s=(ROOT/'qemu/nikon-z8-lab.c').read_text()
  code='\n'.join(function(s,n) for n in ['graphics_color_ready','graphics_color_pixel'])
  check('''#include <glib.h>
#include <stdbool.h>
#include <stdint.h>
#include <math.h>
#include <assert.h>
typedef struct {uint32_t config48[4096],color_tables[6][256];bool color_matrix_valid,color_offset_valid,color_written[6][256];} Z8Graphics;
static int32_t sextract32(uint32_t n,unsigned o,unsigned b){return (int32_t)(n<<(32-o-b))>>(32-b);}
'''+code+'''
int main(void){Z8Graphics g={0};assert(graphics_color_ready(&g));g.config48[0x200]=8;assert(!graphics_color_ready(&g));
unsigned knots[]={0,1,2,3,4,6,8,12,16,24,32,48,64,96,128,192,256,384,512,768,1024,1280,1536,1792,2048,2304,2560,2816,3072,3328,3584,3840,4096};
for(unsigned c=3;c<6;c++)for(unsigned i=0;i<32;i++){g.color_written[c][i]=true;g.color_tables[c][i]=knots[i]|(knots[i+1]-knots[i])<<12;}
assert(graphics_color_ready(&g));for(unsigned i=0;i<256;i++){uint8_t in[]={i,255-i,i/2,37},out[4];graphics_color_pixel(&g,in,out);assert(!memcmp(in,out,4));}
g.color_written[5][31]=false;assert(!graphics_color_ready(&g));g.config48[0x200]=15;assert(!graphics_color_ready(&g));g.config48[0x200]=4;assert(!graphics_color_ready(&g));return 0;}
''')
