# SPDX-License-Identifier: GPL-2.0-or-later
"""Z8's observed internal video bank still requires complete paired headers."""
from pathlib import Path
import unittest
from source_helpers import function
from test_shared221 import check

class VideoHeader(unittest.TestCase):
    def test_z8_bank_and_incomplete_controls(self):
        src=(Path(__file__).resolve().parents[1]/'qemu/nikon-z8-lab.c').read_text()
        production=function(src,'engine1543_video_ready')
        check('''#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
typedef struct {bool engine1543_video_control_model,engine1543_capture_control_model,video_receiver_before_supplier_model,capture_nv16_requested;
uint32_t engine1542_config[15][0x2000/4],engine1542_pending[15],engine1543_valid[3];
uint64_t engine1543_buffer_valid[3];struct {uint32_t config[0x2000/4];} engine1518[3];} NikonZ8State;
'''+production+'''
static void bank(NikonZ8State *s,uint32_t alternate) {
 uint32_t *c=s->engine1542_config[11];
 for(unsigned row=0;row<4;row++)for(unsigned plane=0;plane<2;plane++) {
  unsigned off=0x200+row*0x80+plane*8;
  c[off/4]=0xe0000000u+(row%2?alternate:0)+(plane?2944:0);c[(off+4)/4]=0;
 }
}
int main(void) {
 NikonZ8State s={0};s.engine1543_video_control_model=s.engine1543_capture_control_model=true;
 s.engine1543_valid[1]=15;s.engine1543_buffer_valid[1]=UINT64_C(0x000f000f000f000f);
 uint32_t *c=s.engine1542_config[11],*a=s.engine1542_config[1],*src=s.engine1518[0].config;
 c[1]=0x103;c[2]=0x302;c[4]=0x29;
 a[1]=0x202;a[2]=0x0f010000;a[3]=0x71200410;a[4]=1;
 a[0x4c/4]=1920;a[0x50/4]=1080;a[0x38/4]=a[0x3c/4]=5888;
 src[0xbc/4]=src[0xc0/4]=1;src[0xb0/4]=src[0xb4/4]=5760;
 bank(&s,0xe100);assert(engine1543_video_ready(&s,1));assert(!engine1543_video_ready(&s,0));
 c[0x388/4]++;assert(!engine1543_video_ready(&s,1));bank(&s,0xe100);
 c[0x284/4]=1;assert(!engine1543_video_ready(&s,1));bank(&s,0xe100);
 s.engine1543_buffer_valid[1]^=1;assert(!engine1543_video_ready(&s,1));s.engine1543_buffer_valid[1]^=1;
 s.engine1542_pending[11]=1;assert(!engine1543_video_ready(&s,1));s.engine1542_pending[11]=0;
 src[0xb4/4]++;assert(!engine1543_video_ready(&s,1));src[0xb4/4]--;
 a[0x3c/4]--;assert(!engine1543_video_ready(&s,1));a[0x3c/4]++;
 bank(&s,0xf780);assert(engine1543_video_ready(&s,1));bank(&s,0x43800);assert(engine1543_video_ready(&s,1));
 bank(&s,0xf000);assert(!engine1543_video_ready(&s,1));return 0;
}
''')
