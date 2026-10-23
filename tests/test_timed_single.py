"""Compile Z8 periodic/finite DMA ownership from the production header."""
from pathlib import Path
import unittest
from source_helpers import function
from test_shared221 import check

class TimedSingle(unittest.TestCase):
    def test_periodic_dma_owns_single_request(self):
        source=(Path(__file__).resolve().parents[1]/'qemu/nikon-z8-d980.h').read_text()
        production='\n'.join(function(source,n) for n in
            ['primary_d980_native_live_source','primary_d980_native_single_owner','primary_d980_native_source_config','primary_d980_single_source_ready','primary_d980_source_control','primary_d980_single_arm','primary_d980_single_complete','primary_d980_tick','primary_d980_single_tick'])
        check('''
/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright (C) 2026 RdWing */
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <inttypes.h>
#include <assert.h>
#define QEMU_CLOCK_VIRTUAL 0
typedef struct { void *native_mcu;uint64_t event_control_1508[4],event_mode_1508[17];uint64_t primary_d980_pending;
uint64_t engine150c_active;uint32_t primary_d980_latched[44];bool ready;
uint64_t event_channel_inputs;
uint64_t event_pending_1508;
uint64_t event_timing_active;
uint64_t primary_d980_bytes;
uint64_t primary_d980_channel_boundaries;
uint64_t primary_d980_channel_boundary_model;
uint64_t primary_d980_channel_coalesced;
uint64_t primary_d980_frames;
uint64_t primary_d980_input_epoch;
uint64_t primary_d980_single_armed,primary_d980_single_model,primary_d980_source_start_epoch;
uint64_t primary_d980_single_request_epoch,primary_d980_single_requests;
uint64_t primary_d980_single_attempts,primary_d980_single_source_waits;
uint64_t primary_d980_single_epoch;
uint64_t primary_d980_single_frames;
uint64_t primary_d980_single_timer;
uint64_t primary_d980_source_notifications;
uint64_t primary_d980_source_notify_model;
uint64_t primary_reset_stage;
uint64_t raw_source_boundaries;
uint64_t z8_timed_single_model;
bool z8_still,primary_d980_live_single_model,primary_reset_queued_start_model;
uint64_t engine150c_bit6_pending,engine_150c_primary[16],z8_still_ends;
} NikonZ8State;
static bool primary_d980_ready(NikonZ8State*s){return s->ready;}
static int allow_dma, dma_calls, notify_calls, channel_calls, cancels,video;
static bool primary_d980_receive(NikonZ8State *s, bool single) {(void)single;dma_calls++;if(!allow_dma||s->primary_d980_pending)return false;s->primary_d980_pending=1;s->primary_d980_frames++;s->primary_d980_bytes+=80017920;return true;}
static void raw_source_boundary_receive(NikonZ8State *s,bool v) {(void)v;s->raw_source_boundaries++;notify_calls++;}
static void event_channel_update_irq(NikonZ8State *s) {(void)s;channel_calls++;}
static void primary_d980_single_cancel(NikonZ8State *s){s->primary_d980_single_armed=0;cancels++;}
static uint64_t qemu_clock_get_ns(int v){(void)v;return 0;}
static void timer_mod(uint64_t timer,uint64_t ns){(void)timer;(void)ns;}
static void timer_del(uint64_t t){(void)t;}
static bool video_raw_descriptor(NikonZ8State*s){(void)s;return video;}
static bool primary_d980_finite_input_owned(NikonZ8State*s){return s->primary_d980_single_armed;}
static void engine150c_stop_irq_update(NikonZ8State*s){(void)s;}
static void engine150c_bit6_pulse(NikonZ8State*s){(void)s;}
static void primary_d980_input_trace(NikonZ8State*s,const char*a,uint32_t p,uint32_t v){(void)s;(void)a;(void)p;(void)v;}
''' + production + '''
int main(void){NikonZ8State s={0};s.z8_timed_single_model=1;s.primary_d980_single_armed=1;s.event_timing_active=1;s.engine150c_active=0x4000;s.primary_d980_input_epoch=7;primary_d980_single_arm(&s);assert(s.primary_d980_single_request_epoch==7&&s.primary_d980_single_requests==1);s.primary_d980_source_notify_model=1;s.primary_d980_channel_boundary_model=1;
primary_d980_tick(&s);assert(dma_calls==0&&s.primary_d980_single_armed);
for(int i=0;i<96;i++)primary_d980_single_tick(&s);assert(s.primary_d980_single_armed&&s.primary_d980_single_attempts==0&&s.primary_d980_single_source_waits==96&&dma_calls==0&&cancels==0);
s.event_control_1508[3]=0x201;primary_d980_tick(&s);assert(dma_calls==1&&notify_calls==0&&channel_calls==0&&s.primary_d980_single_armed);
primary_d980_single_tick(&s);assert(cancels==0&&dma_calls==1&&s.primary_d980_single_armed);
allow_dma=1;primary_d980_tick(&s);assert(s.primary_d980_single_frames==1&&s.primary_d980_single_epoch==7&&!s.primary_d980_single_armed);assert(s.primary_d980_bytes==80017920&&notify_calls==1&&channel_calls==1&&s.event_pending_1508==1);
primary_d980_tick(&s);assert(s.primary_d980_single_frames==1&&notify_calls==1);
s.primary_d980_single_armed=1;s.primary_reset_stage=1;primary_d980_single_tick(&s);assert(cancels==1&&!s.primary_d980_single_armed);
s.primary_reset_stage=0;s.primary_d980_single_armed=1;s.z8_timed_single_model=0;primary_d980_single_tick(&s);assert(cancels==2&&!s.primary_d980_single_armed);
s=(NikonZ8State){0};s.primary_d980_single_armed=1;s.engine150c_active=0x4000;s.event_control_1508[3]=0x201;allow_dma=0;int before=dma_calls;for(int i=0;i<65;i++)primary_d980_single_tick(&s);assert(cancels==3&&!s.primary_d980_single_armed&&s.primary_d980_single_attempts==65&&dma_calls==before+64&&s.primary_d980_single_frames==0);
s=(NikonZ8State){0};s.primary_d980_single_armed=1;primary_d980_single_tick(&s);assert(cancels==4&&!s.primary_d980_single_armed);
/* Native input requires the original source START edge of this request. */
s=(NikonZ8State){.native_mcu=&s,.z8_still=true,.z8_timed_single_model=1,
 .primary_d980_single_model=1,.primary_d980_single_armed=1,
 .primary_d980_input_epoch=9,.primary_d980_single_request_epoch=9,
 .engine150c_active=0x401e};
s.event_control_1508[3]=0x4000;s.event_control_1508[0]=1;
assert(!primary_d980_single_source_ready(&s));
primary_d980_source_control(&s,1,0,1);assert(!primary_d980_single_source_ready(&s));
primary_d980_source_control(&s,0,1,1);assert(!primary_d980_single_source_ready(&s));
s.primary_d980_single_request_epoch=8;primary_d980_source_control(&s,0,0,1);
assert(!primary_d980_single_source_ready(&s));s.primary_d980_single_request_epoch=9;
s.event_mode_1508[0]=2;primary_d980_source_control(&s,0,0,1);
assert(!primary_d980_single_source_ready(&s));s.event_mode_1508[0]=0;
primary_d980_source_control(&s,0,0,1);assert(primary_d980_single_source_ready(&s));
video=1;assert(!primary_d980_single_source_ready(&s));video=0;
s.primary_reset_stage=1;assert(!primary_d980_single_source_ready(&s));s.primary_reset_stage=0;
s.native_mcu=0;assert(!primary_d980_single_source_ready(&s));s.native_mcu=&s;
s.primary_d980_input_epoch++;assert(!primary_d980_single_source_ready(&s));s.primary_d980_input_epoch--;
s.event_control_1508[3]=0x7008;assert(!primary_d980_single_source_ready(&s));
s.event_control_1508[3]=0x7009;s.event_timing_active=1;
assert(primary_d980_single_source_ready(&s));
allow_dma=1;before=dma_calls;primary_d980_single_tick(&s);
assert(dma_calls==before+1&&s.primary_d980_single_frames==1&&s.primary_d980_single_epoch==9);
primary_d980_single_tick(&s);assert(dma_calls==before+1);
s.primary_d980_single_armed=1;before=cancels;primary_d980_source_control(&s,0,1,0);
assert(cancels==before+1&&!s.primary_d980_single_armed);
/* The explicit native live profile consumes a later periodic frame only.
 * Invalid source/generation/descriptor/reset/movie cases never admit DMA. */
s=(NikonZ8State){.native_mcu=&s,.z8_still=true,.z8_timed_single_model=1,
 .primary_d980_live_single_model=true,.primary_d980_single_model=1,
 .primary_d980_single_armed=1,.primary_d980_input_epoch=12,
 .primary_d980_single_request_epoch=12,.event_timing_active=1,
 .engine150c_active=0x77f7f,.event_control_1508={1,0,0,0x704b},.ready=true,
 .primary_d980_latched={2,8280u<<16,5520u<<16,0,12448}};
assert(primary_d980_native_live_source(&s));
s.primary_d980_live_single_model=false;assert(!primary_d980_native_live_source(&s));s.primary_d980_live_single_model=true;
s.primary_d980_single_request_epoch--;assert(!primary_d980_native_live_source(&s));s.primary_d980_single_request_epoch++;
s.event_timing_active=0;assert(!primary_d980_native_live_source(&s));s.event_timing_active=1;
s.event_control_1508[0]=0;assert(!primary_d980_native_live_source(&s));s.event_control_1508[0]=1;
s.event_control_1508[3]=0x7009;assert(!primary_d980_native_live_source(&s));s.event_control_1508[3]=0x704b;
s.event_mode_1508[0]=2;assert(!primary_d980_native_live_source(&s));s.event_mode_1508[0]=0;
s.primary_reset_stage=1;assert(!primary_d980_native_live_source(&s));s.primary_reset_stage=0;
s.engine150c_active=0x401e;assert(!primary_d980_native_live_source(&s));s.engine150c_active=0x77f7f;
s.primary_d980_latched[0]=1;assert(!primary_d980_native_live_source(&s));s.primary_d980_latched[0]=2;
s.primary_d980_latched[4]++;assert(!primary_d980_native_live_source(&s));s.primary_d980_latched[4]--;
s.primary_d980_latched[1]-=1u<<16;assert(!primary_d980_native_live_source(&s));s.primary_d980_latched[1]+=1u<<16;
s.primary_d980_latched[2]-=1u<<16;assert(!primary_d980_native_live_source(&s));s.primary_d980_latched[2]+=1u<<16;
s.native_mcu=0;assert(!primary_d980_native_live_source(&s));s.native_mcu=&s;
s.primary_d980_single_armed=0;assert(!primary_d980_native_live_source(&s));s.primary_d980_single_armed=1;

s.ready=false;assert(!primary_d980_native_live_source(&s));s.ready=true;
video=1;assert(!primary_d980_native_live_source(&s));video=0;
before=dma_calls;allow_dma=0;primary_d980_tick(&s);
assert(s.primary_d980_single_armed&&s.primary_d980_single_frames==0&&dma_calls==before+1);
allow_dma=1;primary_d980_tick(&s);
assert(!s.primary_d980_single_armed&&s.primary_d980_single_frames==1&&s.primary_d980_single_epoch==12);
primary_d980_tick(&s);assert(dma_calls==before+2);
s.primary_d980_single_armed=1;s.primary_d980_pending=0;s.primary_d980_single_attempts=0;
allow_dma=0;before=dma_calls;int old_cancels=cancels;
for(int i=0;i<65;i++)primary_d980_tick(&s);
assert(!s.primary_d980_single_armed&&s.primary_d980_single_attempts==65&&dma_calls==before+64&&cancels==old_cancels+1&&s.primary_d980_single_frames==1);

return 0;}
''')
