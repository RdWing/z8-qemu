#!/usr/bin/env python3
# Copyright (C) 2026 RdWing: Z8 adaptation.
"""Admission for the production native HE still FIFO, without firmware."""
from test_shared221 import SOURCE, check
import unittest

class HEStillFIFO(unittest.TestCase):
    def test_receiver_ownership_and_whole_output_bounds(self):
        s=(SOURCE/'nikon-z8-lab.c').read_text()
        source=s[s.index('static bool engine152c_he_ready('):s.index('static bool engine151_raw_output_ready(')]
        check(r'''
#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
#define MiB (1024u*1024u)
typedef struct {
 bool engine152c_he_still_model,engine152c_stream_model,engine152c_request_pending,engine152c_he_pending;
 uint64_t engine152c_he_acks;
 uint32_t engine152c_stream_pending,engine152c_config[2][0x600/4];
 uint64_t engine152c_request_in,engine152c_request_out;
 unsigned engine152c_request_capacity,engine152c_request_codec;
 unsigned engine152c_request_width,engine152c_request_height,engine152c_request_pitch;
} NikonZ8State;
static bool dma_ram_range(NikonZ8State*s,uint64_t a,uint64_t n)
{(void)s;return a>=0x840000000ULL && n<=0x900000000ULL-a;}
'''+source+r'''
int main(void) {
 NikonZ8State s={.engine152c_he_still_model=true,.engine152c_stream_model=true,
 .engine152c_request_pending=true,.engine152c_request_in=0xe0000000,
 .engine152c_request_out=0x8fea3c200ULL,.engine152c_request_capacity=0xe9a200,
 .engine152c_request_codec=1,.engine152c_request_width=6064,
 .engine152c_request_height=4040,.engine152c_request_pitch=10624};
 uint32_t m[0x500/4]={0};m[0x400/4]=4040u<<16|6064;m[0x430/4]=10624;
 s.engine152c_config[0][8/4]=1;s.engine152c_config[0][0x14/4]=1;
 s.engine152c_config[1][0x38/4]=1;
 uint32_t*c=s.engine152c_config[0],*d=s.engine152c_config[1];
 c[0x52c/4]=1;c[0x530/4]=1;c[0x548/4]=6064;c[0x54c/4]=4040;
 c[0x544/4]=10624;c[0x550/4]=d[0x44/4]=0xe9a200;
 c[0x120/4]=0xfea3c200;c[0x124/4]=8;c[0x220/4]=0xe0000000;
 #define READY() engine152c_he_ready(&s,m,0x8afb97000ULL,42920960,0x8c696ba00ULL,0x8c80cca00ULL,24385536)
 assert(READY());s.engine152c_he_still_model=false;assert(!READY());s.engine152c_he_still_model=true;
 s.engine152c_request_pending=false;assert(!READY());s.engine152c_request_pending=true;
 s.engine152c_stream_pending=4;assert(!READY());s.engine152c_stream_pending=0;
 s.engine152c_request_in=0x8afb97000ULL;assert(!READY());s.engine152c_request_in=0xe0000000;
 s.engine152c_request_width++;assert(!READY());s.engine152c_request_width--;
 s.engine152c_request_pitch+=32;assert(!READY());s.engine152c_request_pitch-=32;
 s.engine152c_request_codec=2;assert(!READY());s.engine152c_request_codec=1;
 uint64_t dest=s.engine152c_request_out;
 #define DEST(v) do {s.engine152c_request_out=(v);c[0x120/4]=(uint32_t)(v);c[0x124/4]=(uint64_t)(v)>>32;}while(0)
 DEST(0x8afb97000ULL);assert(!READY());
 DEST(0x8c696ba00ULL);assert(!READY());
 DEST(0x8c80cca00ULL);assert(!READY());
 DEST(0x8ffffffffULL);assert(!READY());DEST(dest);
 s.engine152c_request_capacity=33*MiB;assert(!READY());
 assert(!engine152c_he_ack(&s,6));
 s.engine152c_he_pending=true;s.engine152c_stream_pending=6;
 assert(engine152c_he_ack(&s,0)&&s.engine152c_he_pending&&!s.engine152c_he_acks);
 assert(engine152c_he_ack(&s,2)&&s.engine152c_he_pending&&!s.engine152c_he_acks);
 s.engine152c_stream_pending&=~2;
 assert(engine152c_he_ack(&s,4)&&!s.engine152c_he_pending&&s.engine152c_he_acks==1);
 assert(!engine152c_he_ack(&s,6)&&s.engine152c_he_acks==1);
 s.engine152c_he_pending=true;s.engine152c_stream_pending=6;
 assert(engine152c_he_ack(&s,6)&&!s.engine152c_he_pending&&s.engine152c_he_acks==2);
 return 0;
}
''')

if __name__=='__main__':unittest.main()
