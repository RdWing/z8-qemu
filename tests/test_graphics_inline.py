# SPDX-License-Identifier: GPL-2.0-or-later
"""Both observed empty-inline families retain matched end and draw ownership."""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from source_helpers import ROOT, function

class GraphicsInline(unittest.TestCase):
    def test_original_empty_pair_and_nonempty_rejection(self):
        source=(ROOT/'qemu/nikon-z8-lab.c').read_text()
        code=r'''
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <string.h>
typedef struct {
 bool image_pending,path_pending,path_controls[2];
 unsigned inline_path_phase,inline_path_end,image_selector,path_kind;
 unsigned path_paint_valid,path_paint_mask,path_edge_count,path_descriptors;
 uint64_t path_program;
} Z8Graphics;
'''+function(source,'graphics_inline_packet_allowed')+function(source,'graphics_inline_path')+r'''
static Z8Graphics ready(void){return (Z8Graphics){.path_controls={true,false},.path_kind=2,.path_paint_valid=3,.path_paint_mask=1,.path_program=0x1000,.path_edge_count=77};}
int main(void){
 for(unsigned family=0;family<2;family++){
  unsigned begin=family?0xe73:0x5e5,end=family?0xe85:0x5ec;
  Z8Graphics g=ready();assert(graphics_inline_path(&g,begin));
  assert(g.inline_path_phase==1&&g.inline_path_end==end&&g.path_edge_count==0);
  assert(!g.path_pending&&!g.path_descriptors);
  assert(!graphics_inline_packet_allowed(&g,0x80000001));
  assert(!graphics_inline_packet_allowed(&g,0x430ac001));
  assert(!graphics_inline_packet_allowed(&g,0xa8000000));
  assert(graphics_inline_packet_allowed(&g,0xa0000000|(end<<7)));
  g.image_selector=end;assert(graphics_inline_packet_allowed(&g,0xa8000000));
  Z8Graphics before;memcpy(&before,&g,sizeof g);assert(!graphics_inline_path(&g,begin));assert(!memcmp(&g,&before,sizeof g));
  assert(!graphics_inline_path(&g,family?0x5ec:0xe85));assert(!memcmp(&g,&before,sizeof g));
  assert(graphics_inline_path(&g,end));assert(g.path_pending&&g.path_descriptors==1&&!g.inline_path_phase&&!g.inline_path_end);
  memcpy(&before,&g,sizeof g);assert(!graphics_inline_path(&g,begin));assert(!memcmp(&g,&before,sizeof g));
 }
 for(unsigned bad=0;bad<7;bad++){
  Z8Graphics g=ready();
  switch(bad){case 0:g.path_controls[0]=false;break;case 1:g.path_kind=3;break;case 2:g.path_paint_valid=2;break;case 3:g.path_program=0;break;case 4:g.image_pending=true;break;case 5:g.path_pending=true;break;case 6:g.path_paint_mask=0;}
  Z8Graphics before;memcpy(&before,&g,sizeof g);assert(!graphics_inline_path(&g,0xe73));assert(!memcmp(&g,&before,sizeof g));
 }
 Z8Graphics g=ready(),before;memcpy(&before,&g,sizeof g);assert(!graphics_inline_path(&g,0xe85));assert(!graphics_inline_path(&g,0xe74));assert(!memcmp(&g,&before,sizeof g));
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);src=root/'inline.c';exe=root/'inline';src.write_text(code)
            subprocess.run([os.environ.get('CC','cc'),'-Wall','-Wextra','-Werror','-fsanitize=address,undefined',str(src),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)
