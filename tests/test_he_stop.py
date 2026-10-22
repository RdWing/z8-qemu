# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Finite HE STOP must follow completed output and preserve owners."""
import unittest
from source_helpers import ROOT, function
from test_shared221 import check

class HEStop(unittest.TestCase):
    def test_stop_ownership(self):
        text=(ROOT/'qemu/nikon-z8-lab.c').read_text()
        production='\n'.join(function(text,n) for n in ['engine152c_he_stop_control','engine152c_he_stop_tick'])
        check('''#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
typedef uint64_t hwaddr;
typedef struct {bool video_raw_transport_model,video_backend_locally_disabled[2];
bool engine152c_he_still_model,engine152c_request_pending,engine152c_he_pending,engine152c_stream_requested,engine152c_he_stop_pending,engine152c_he_stop_done;
uint32_t engine152c_config[2][384],engine152c_stream_pending,engine150c_active;
uint64_t engine152c_stream_timer;
uint64_t engine152c_he_acks,engine152c_he_stop_requests,engine152c_he_stop_events;} NikonZ8State;
static int rejects,irqs;
#define QEMU_CLOCK_VIRTUAL 0
static uint64_t qemu_clock_get_ns(int x){(void)x;return 0;}
static void timer_mod(uint64_t t,uint64_t n){(void)t;(void)n;}
static void unknown_access(NikonZ8State*s,hwaddr a,uint64_t v,unsigned n,bool w){(void)s;(void)a;(void)v;(void)n;(void)w;rejects++;}
static void engine152c_stream_irq_update(NikonZ8State*s){(void)s;irqs++;}
'''+production+'''
int main(void){NikonZ8State s={0};
assert(!engine152c_he_stop_control(&s,0x152c000c,1,4));
s.engine152c_he_still_model=true;s.video_raw_transport_model=true;s.engine152c_stream_requested=true;
assert(!engine152c_he_stop_control(&s,0x152c000c,1,4)&&rejects==0);s.engine152c_stream_requested=false;s.video_raw_transport_model=false;
s.engine152c_config[0][0x404/4]=1;s.engine152c_config[0][2]=1;
engine152c_he_stop_control(&s,0x152c000c,1,4);assert(rejects==1&&!s.engine152c_he_stop_pending);
s.engine152c_he_acks=1;s.engine152c_he_pending=true;
engine152c_he_stop_control(&s,0x152c000c,1,4);assert(rejects==2);
s.engine152c_he_pending=false;s.engine150c_active=0x4000;
engine152c_he_stop_control(&s,0x152c000c,1,4);assert(rejects==3);
s.engine150c_active=0;s.engine152c_stream_pending=4;
engine152c_he_stop_control(&s,0x152c000c,1,4);assert(rejects==4&&s.engine152c_stream_pending==4);
s.engine152c_stream_pending=0;
engine152c_he_stop_control(&s,0x152c000c,1,4);assert(rejects==4&&s.engine152c_he_stop_requests==1&&s.engine152c_he_stop_pending&&!irqs);
engine152c_he_stop_control(&s,0x152c000c,1,4);assert(rejects==5);
s.engine152c_stream_pending=2;engine152c_he_stop_tick(&s);assert(!irqs&&s.engine152c_stream_pending==2);
s.engine152c_stream_pending=0;engine152c_he_stop_tick(&s);assert(irqs==1&&s.engine152c_he_stop_events==1&&s.engine152c_stream_pending==8&&s.engine152c_config[0][3]==0);
engine152c_he_stop_tick(&s);assert(irqs==1);
return 0;}
''')
