# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Movie receiver admission after an HE still retains ownership fences."""
import unittest
from source_helpers import ROOT, function
from test_shared221 import check


class MovieReceiver(unittest.TestCase):
    def test_he_selector_and_receiver_fences(self):
        source = (ROOT / 'qemu/nikon-z8-lab.c').read_text()
        check('''#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <assert.h>
#define MiB (1024u*1024u)
typedef struct {
 bool engine152c_stream_model,engine152c_stream_requested,engine152c_request_pending;
 bool video_raw_he_codec_model,video_raw_receiver_banks_model,video_raw_receiver_wait_bank;
 bool backend_program_epoch_model,backend_program_dirty,video_backend_locally_disabled[2];
 uint32_t engine152c_config[2][384],engine152c_stream_pending,engine152c_fifo_words;
 uint32_t engine152c_stream_outputs_valid,video_raw_receiver_bank,video_raw_receiver_fresh;
 uint32_t engine152c_stream_inputs_valid,engine152c_stream_capacity,engine152c_stream_row;
 uint32_t engine152c_stream_width,engine152c_stream_height;
 uint32_t video_raw_receiver_left,video_raw_receiver_top,video_raw_receiver_mode;
 uint64_t engine152c_stream_outputs[4],backend_program_latches,backend_program_uploads;
 uint64_t engine152c_stream_requests;
} NikonZ8State;
static bool raw_pipeline_address(NikonZ8State*s,uint64_t encoded,uint32_t bytes,uint64_t*out){
 (void)s;if(encoded<0xc00000000ULL || encoded+bytes>0xd00000000ULL)return false;
 *out=encoded-0x400000000ULL;return true;
}
''' + function(source, 'engine152c_stream_start') + '''
static NikonZ8State ready(void){
 NikonZ8State s={0};s.engine152c_stream_model=true;
 uint32_t*c=s.engine152c_config[0],*d=s.engine152c_config[1];
 c[0x14/4]=d[0x38/4]=c[0x100/4]=c[0x104/4]=1;
 c[0x548/4]=d[0x14/4]=4140;c[0x54c/4]=d[0x1c/4]=2344;
 c[0x550/4]=d[0x44/4]=0x4a0800;d[0x48/4]=14;
 s.engine152c_fifo_words=14;s.engine152c_stream_outputs_valid=255;
 for(unsigned row=0;row<4;row++){
  c[(0x120+row*8)/4]=0x10000000+row*0x1000000;c[(0x124+row*8)/4]=0xc;
 }
 return s;
}
int main(void){
 NikonZ8State s=ready();assert(engine152c_stream_start(&s));
 s=ready();s.engine152c_config[0][0x530/4]=1;
 assert(!engine152c_stream_start(&s)&&!s.engine152c_stream_requests);
 s.video_raw_he_codec_model=true;s.engine152c_stream_inputs_valid=65535;
 assert(engine152c_stream_start(&s)&&s.engine152c_stream_requests==1);
 assert(!s.engine152c_stream_inputs_valid&&s.engine152c_stream_requested);
 assert(!engine152c_stream_start(&s));
 for(unsigned selector=2;selector<8;selector++){
  s=ready();s.video_raw_he_codec_model=true;s.engine152c_config[0][0x530/4]=selector;
  assert(!engine152c_stream_start(&s)&&!s.engine152c_stream_requests);
 }
 for(unsigned invalid=0;invalid<7;invalid++){
  s=ready();s.video_raw_he_codec_model=true;s.engine152c_config[0][0x530/4]=1;
  switch(invalid){
   case 0:s.engine152c_stream_pending=4;break;
   case 1:s.engine152c_request_pending=true;break;
   case 2:s.engine152c_stream_outputs_valid=127;break;
   case 3:s.engine152c_config[0][0x128/4]=s.engine152c_config[0][0x120/4];break;
   case 4:s.engine152c_config[0][0x124/4]=0xe;break;
   case 5:s.engine152c_config[0][0x52c/4]=1;break;
   case 6:s.engine152c_config[1][0x44/4]++;break;
  }
  assert(!engine152c_stream_start(&s)&&!s.engine152c_stream_requests&&!s.engine152c_stream_requested);
 }
 return 0;
}
''')
