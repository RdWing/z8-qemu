# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Fresh live-HE submissions rearm once; old pixels and pending owners do not."""
import unittest
from source_helpers import ROOT, function
from test_shared221 import check


class LiveSingleRearm(unittest.TestCase):
    def test_submission_and_front_own_a_fresh_epoch(self):
        text = (ROOT / 'qemu/nikon-z8-d980.h').read_text()
        production = '\n'.join(function(text, name) for name in [
            'primary_d980_description', 'primary_d980_descriptor_ready',
            'primary_d980_live_rearm', 'primary_d980_single_arm',
            'primary_d980_single_mode'])
        check('''#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <assert.h>
#include <stdio.h>
#include <inttypes.h>
#define MiB (1024u*1024u)
#define NIKON_RAW_MAX_DIMENSION 16384
#define NIKON_RAW_MAX_SAMPLES 50000000
#define QEMU_CLOCK_VIRTUAL 0
typedef struct {struct {uint64_t pc,xregs[32];} env;} CPU;
static CPU *current_cpu;
#define ARM_CPU(c) (c)
typedef struct {
 void *native_mcu,*raw_pixels;
 bool primary_d980_live_single_model,primary_d980_packed14_model,z8_still;
 bool z8_timed_single_model,primary_d980_single_model,primary_d980_single_armed;
 bool primary_d980_prepared_start_model,primary_d980_prepared;
 bool engine150c_stop_reset_asserted,engine152c_he_still_model;
 bool engine152c_he_pending,engine152c_request_pending,engine152c_he_stop_pending;
 bool engine152c_stream_requested;
 uint32_t engine152c_stream_pending,engine150c_active,primary_reset_stage;
 uint32_t engine150c_stop_requested,primary_d980_pending;
 uint32_t primary_d980_submitted[28],primary_d980_latched[28],engine_150c_init[256];
 uint32_t event_control_1508[4];bool event_timing_active;unsigned primary_d980_slot;
 uint64_t primary_d980_input_epoch,primary_d980_single_epoch,primary_d980_single_submit;
 uint64_t primary_d980_submits,primary_d980_latched_submit,primary_d980_live_rearms,primary_d980_single_frames;
 uint64_t engine152c_he_jobs,engine152c_he_acks,engine152c_he_stop_acks;
 uint64_t primary_d980_single_request_epoch,primary_d980_single_requests;
 unsigned primary_d980_single_attempts;
 uint64_t primary_d980_single_timer,primary_reset_count,primary_d980_prepare_requests;
} NikonZ8State;
static bool video;
static bool video_raw_descriptor(NikonZ8State*s){(void)s;return video;}
static bool raw_pipeline_address(NikonZ8State*s,uint64_t e,uint64_t n,uint64_t*p){
 (void)s;if(e<0xc00000000ull||e+n>0xc08000000ull)return false;*p=e-0x400000000ull;return true;
}
static void primary_d980_input_trace(NikonZ8State*s,const char*a,uint32_t p,uint32_t v){(void)s;(void)a;(void)p;(void)v;}
static uint64_t qemu_clock_get_ns(int c){(void)c;return 0;}
static void timer_mod(uint64_t t,uint64_t ns){(void)t;(void)ns;}
''' + production + '''
static NikonZ8State good(void){
 NikonZ8State s={0};s.native_mcu=s.raw_pixels=(void*)1;
 s.primary_d980_live_single_model=s.primary_d980_packed14_model=s.z8_still=true;
 s.z8_timed_single_model=s.primary_d980_single_model=true;
 s.engine152c_he_still_model=true;s.engine150c_active=0x77f7f;
 s.primary_d980_input_epoch=s.primary_d980_single_epoch=s.primary_d980_single_submit=1;
 s.primary_d980_single_frames=1;s.primary_d980_submits=2;s.primary_d980_latched_submit=1;s.primary_d980_single_requests=1;
 s.engine152c_he_jobs=s.engine152c_he_acks=s.engine152c_he_stop_acks=1;
 s.event_timing_active=true;s.event_control_1508[0]=1;s.event_control_1508[3]=0x724b;
 s.primary_d980_pending=0x4000000;s.primary_d980_slot=3;
 uint32_t d[28]={1,8280u<<16,5520u<<16,0,14496,1,1,0,1,0,0,0,0x1000,12};
 memcpy(s.primary_d980_submitted,d,sizeof(d));return s;
}
#define REFUSE(change) do {NikonZ8State s=good();change;NikonZ8State before=s;assert(!primary_d980_live_rearm(&s));assert(!memcmp(&s,&before,sizeof(s)));} while(0)
int main(void){
 REFUSE(s.primary_d980_live_single_model=false);REFUSE(s.native_mcu=NULL);
 REFUSE(s.z8_still=false);REFUSE(s.z8_timed_single_model=false);
 REFUSE(s.primary_d980_single_model=false);REFUSE(s.primary_d980_single_armed=true);
 REFUSE(s.primary_d980_prepared=true);REFUSE(s.primary_d980_input_epoch=0);
 REFUSE(s.primary_d980_single_epoch=0);REFUSE(s.primary_d980_single_submit=0);
 REFUSE(s.primary_d980_submits=1);REFUSE(s.primary_reset_stage=1);
 REFUSE(s.engine150c_stop_requested=0x4000);REFUSE(s.engine150c_stop_reset_asserted=true);
 REFUSE(s.engine150c_active=0x401e);REFUSE(s.event_timing_active=false);
 REFUSE(s.event_control_1508[0]=0);REFUSE(s.event_control_1508[3]=0x704b);
 REFUSE(s.engine152c_he_still_model=false);REFUSE(s.engine152c_he_jobs=0);
 REFUSE(s.primary_d980_single_frames=2);REFUSE(s.engine152c_he_acks=0);REFUSE(s.engine152c_he_stop_acks=0);
 REFUSE(s.engine152c_he_pending=true);REFUSE(s.engine152c_request_pending=true);
 REFUSE(s.engine152c_he_stop_pending=true);REFUSE(s.engine152c_stream_requested=true);
 REFUSE(s.engine152c_stream_pending=4);REFUSE(s.primary_d980_pending|=1);
 REFUSE(s.engine_150c_init[0x20c/4]=0x4000000);
 REFUSE(s.primary_d980_submitted[4]++);REFUSE(s.raw_pixels=NULL);
 REFUSE(s.primary_d980_submitted[14]=1);REFUSE(s.primary_d980_submitted[13]=13);
 video=true;REFUSE((void)0);video=false;
 NikonZ8State s=good(),before=s;
 primary_d980_single_mode(&s,1,2,3);assert(!memcmp(&s,&before,sizeof(s)));
 primary_d980_single_mode(&s,0,0,3);assert(!memcmp(&s,&before,sizeof(s)));
 primary_d980_single_mode(&s,0,2,3);
 assert(s.primary_d980_input_epoch==2&&s.primary_d980_live_rearms==1&&s.primary_d980_latched_submit==2);
 assert(s.primary_d980_single_armed&&s.primary_d980_single_request_epoch==2);
 assert(s.primary_d980_single_requests==2&&!s.primary_d980_pending&&!s.primary_d980_slot);
 assert(!memcmp(s.primary_d980_latched,s.primary_d980_submitted,sizeof(s.primary_d980_latched)));
 assert(s.engine152c_he_jobs==1&&s.engine152c_he_acks==1&&s.engine152c_he_stop_acks==1);
 before=s;primary_d980_single_mode(&s,0,2,3);assert(!memcmp(&s,&before,sizeof(s)));
 s.primary_d980_single_frames=2;s.primary_d980_single_armed=false;s.primary_d980_single_epoch=2;s.primary_d980_single_submit=2;
 s.engine152c_he_jobs=s.engine152c_he_acks=s.engine152c_he_stop_acks=2;
 before=s;primary_d980_single_mode(&s,0,2,3);assert(!memcmp(&s,&before,sizeof(s)));
 s.primary_d980_submits=3;s.primary_d980_pending=0x4000000;
 primary_d980_single_mode(&s,0,2,3);assert(s.primary_d980_input_epoch==3&&s.primary_d980_live_rearms==2&&s.primary_d980_single_requests==3);
 return 0;
}
''')
