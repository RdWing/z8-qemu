#!/usr/bin/env python3
# Copyright (C) 2026 RdWing: Z8 adaptation.
"""Production shared221 ownership and programmed-clock controls."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'qemu'


def check(code):
    with tempfile.TemporaryDirectory() as temp:
        p=Path(temp);(p/'test.c').write_text(code)
        flags=subprocess.check_output(['pkg-config','--cflags','--libs','glib-2.0'],text=True).split()
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Wno-unused-function',
                        '-fsanitize=address,undefined',str(p/'test.c'),'-o',str(p/'test'),*flags],check=True)
        subprocess.run([str(p/'test')],check=True)


class Shared221(unittest.TestCase):
    def test_pool_ownership_count_commit_and_recycle(self):
        source=(SOURCE/'nikon-expeed-capture-pool.h').read_text().split('static bool get_capture_frame_pool')[0]
        pre=r'''
#include <glib.h>
#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
#define MiB (1024u*1024u)
#define MEMTXATTRS_UNSPECIFIED 0
#define MEMTX_OK 0
static int address_space_memory;
static int address_space_read(void*a,uint64_t b,int c,void*d,uint64_t e)
{(void)a;(void)b;(void)c;memset(d,0,e);return 0;}
static bool dma_ram_range(void*s,uint64_t a,uint64_t n){(void)s;return a&&n;}
typedef struct {
 bool valid,committed,thumbnail_used;
 unsigned kind,output,width,height,stride;
 uint64_t generation,serial,y,uv,count_passes,commits;
} Ex7CaptureSurface;
typedef struct {
 bool capture_frame_pool_model,engine15e2_preflight_model;
 Ex7CaptureSurface capture_surfaces[4];
 uint64_t capture_pool_productions,capture_nv16_jobs,capture_thumbnail_jobs;
 uint64_t capture_nv16_jpeg_consumed[3],engine15e2_count_jobs,engine15e2_thumbnail_consumed;
 uint32_t engine15e2_config[2][0x500/4];
} NikonZ8State;
'''
        checks=r'''
int main(void){
 NikonZ8State s={.capture_frame_pool_model=true,.capture_nv16_jobs=7};
 uint64_t addresses[]={0x1000,0x2000},bytes[]={256,256};
 assert(capture_pool_writable(&s,addresses,bytes,2,1));
 capture_pool_record(&s,0,1,7,0x1000,0x2000,16,16,16);
 assert(!capture_pool_writable(&s,addresses,bytes,2,1));
 assert(!capture_pool_writable(&s,addresses,bytes,0,4));
 assert(capture_pool_thumbnail_source(&s,0x1000,0x2000,16,16,16)==0);
 for(unsigned b=0;b<2;b++){
  uint32_t*c=s.engine15e2_config[b];c[0x430/4]=0x100;c[0x434/4]=0x200;
  c[0x418/4]=c[0x41c/4]=c[0x410/4]=c[0x414/4]=16;
  assert(capture_pool_jpeg_owner(&s,b)==8);
 }
 assert(capture_pool_small_owner(&s,8));
 assert(!capture_pool_small_owner(&s,7));assert(!capture_pool_small_owner(&s,12));
 capture_pool_jpeg_complete(&s,8,true);
 assert(s.capture_surfaces[0].count_passes==1&&!s.capture_surfaces[0].committed);
 assert(!s.capture_nv16_jpeg_consumed[1]);
 assert(!capture_pool_writable(&s,addresses,bytes,2,1));
 capture_pool_jpeg_complete(&s,8,false);
 assert(s.capture_nv16_jpeg_consumed[1]==7);
 assert(capture_pool_jpeg_owner(&s,0)==-1);
 assert(capture_pool_writable(&s,addresses,bytes,2,1));
 s.engine15e2_preflight_model=true;assert(capture_pool_jpeg_owner(&s,0)==8);
 capture_pool_record(&s,0,2,8,0x1000,0x2000,16,16,16);
 assert(s.capture_surfaces[0].generation==8&&!s.capture_surfaces[0].committed);
 assert(!s.capture_surfaces[0].count_passes&&s.capture_pool_productions==2);
 return 0;
}
'''
        check(pre+source+checks)

    def test_programmed_clock_enable_pending_and_coalescing(self):
        source=(SOURCE/'nikon-expeed-programmed-clock.h').read_text().split('static bool get_event_programmed_clock_model')[0]
        pre=r'''
#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <string.h>
typedef struct {
 bool event_programmed_clock_model,bootstrap_fixtures,event1508_channel_model;
 bool event1508_timing_model,event_timing_active;
 uint32_t event_active_1508[15][13],event_control_1508[4],event_output_group_running,event_pending_1508;
 uint64_t event_programmed_clock_ticks[15],event_programmed_clock_coalesced[15],event_programmed_clock_events[15];
} NikonZ8State;
'''
        checks=r'''
int main(void){
 NikonZ8State s={.event_programmed_clock_model=true,.bootstrap_fixtures=true,
 .event1508_channel_model=true,.event1508_timing_model=true,.event_timing_active=true};
 uint32_t*c=s.event_active_1508[2];c[7]=0x06011020;c[0]=c[1]=c[4]=c[5]=1;
 assert(programmed_clock_configured_mask(&s)==4);
 programmed_clock_tick(&s);assert(!s.event_pending_1508);
 s.event_control_1508[3]=4;s.event_output_group_running=4;
 programmed_clock_tick(&s);assert(s.event_pending_1508==4&&s.event_programmed_clock_events[2]==1);
 programmed_clock_tick(&s);assert(s.event_programmed_clock_coalesced[2]==1&&s.event_programmed_clock_events[2]==1);
 s.event_pending_1508&=~4u;programmed_clock_tick(&s);assert(s.event_programmed_clock_events[2]==2);
 s.event_timing_active=false;programmed_clock_tick(&s);assert(s.event_programmed_clock_ticks[2]==3);
 s.event_timing_active=true;c[7]=0x06011001;assert(!programmed_clock_configured_mask(&s));
 c[7]=0x06011000;c[0]=0;assert(!programmed_clock_configured_mask(&s));
 assert(!s.event_programmed_clock_events[0]&&!s.event_programmed_clock_events[1]);
 return 0;
}
'''
        check(pre+source+checks)

if __name__=='__main__':unittest.main()
