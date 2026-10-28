# SPDX-License-Identifier: GPL-2.0-or-later
"""The optional Z8 sensor clock feeds owners without enabling capture group 0."""
from pathlib import Path
import unittest
from source_helpers import function
from test_shared221 import check

class SensorClock(unittest.TestCase):
    def test_separate_capture_and_sensor_clocks(self):
        s=(Path(__file__).resolve().parents[1]/'qemu/nikon-z8-lab.c').read_text()
        production='\n'.join(function(s[s.rindex('static bool z8_sensor_timing('):] if n=='z8_sensor_timing' else s[s.rindex('static void z8_sensor_frame('):] if n=='z8_sensor_frame' else s,n) for n in ['z8_sensor_timing','source_input_clock_running','z8_sensor_source_tick','z8_sensor_frame'])
        check('''#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <stdio.h>
typedef struct {bool event_timing_active,z8_sensor_source_clock,z8_sensor_vd,z8_sensor_started,event1508_timing_model;
bool raw_pipeline_output_done,raw_pipeline_model,engine152c_stream_requested;unsigned z8_raw_owed,primary_reset_stage;uint32_t engine_150c_init[16];uint64_t z8_sensor_source_ticks;bool event1508_global0_model;uint64_t event_channel_inputs,event_global0_inputs,z8_sensor_frames;uint32_t event_pending_1508,event_global0_pending;uint64_t event_timing_period_ns;uint32_t engine150c_active,engine150c_stop_requested,event_control_1508[4];} NikonZ8State;
static void event_channel_update_irq(NikonZ8State*s){(void)s;}
static void event_global0_update_irq(NikonZ8State*s){(void)s;}
static unsigned boundaries,inputs,pixels;static bool descriptor;
static bool video_raw_descriptor(NikonZ8State*s){(void)s;return descriptor;}
static void raw_pipeline_tick(NikonZ8State*s){(void)s;pixels++;}
static void raw_source_boundary_tick(NikonZ8State *s){(void)s;boundaries++;}
static void primary_d980_tick(NikonZ8State *s){(void)s;inputs++;}
'''+production+'''
int main(void) {
 NikonZ8State s={0};s.z8_sensor_vd=s.z8_sensor_started=s.event1508_timing_model=true;
 s.event_timing_period_ns=33333333;s.engine150c_active=2;s.event_control_1508[3]=1;
 assert(z8_sensor_timing(&s));assert(!source_input_clock_running(&s));z8_sensor_source_tick(&s);assert(!inputs);
 s.raw_pipeline_output_done=s.raw_pipeline_model=true;s.z8_sensor_source_clock=true;assert(source_input_clock_running(&s));z8_sensor_frame(&s);
 assert(pixels==1&&s.z8_raw_owed==1&&s.event_pending_1508==1&&s.event_channel_inputs==1);assert(inputs==1&&boundaries==1&&!s.event_timing_active&&s.event_control_1508[0]==0);
 s.event_timing_active=true;z8_sensor_source_tick(&s);assert(inputs==1&&source_input_clock_running(&s));
 s.event_timing_active=false;s.engine150c_stop_requested=2;z8_sensor_source_tick(&s);assert(inputs==1&&!source_input_clock_running(&s));
 s.engine150c_stop_requested=0;s.event_control_1508[3]=0;z8_sensor_source_tick(&s);assert(inputs==1&&!source_input_clock_running(&s));
 s.event_control_1508[3]=1;s.event_timing_period_ns=0;z8_sensor_source_tick(&s);assert(inputs==1&&!source_input_clock_running(&s));
 return 0;
}
''')

    def test_source_restart_reschedules_without_rewinding_pending_clock(self):
        s=(Path(__file__).resolve().parents[1]/'qemu/nikon-z8-lab.c').read_text()
        production=function(s[s.rindex('static bool z8_sensor_timing('):],'z8_sensor_timing')+'\n'+function(s[s.index('static void event_timing_update(NikonZ8State *s)\n{'):],'event_timing_update')
        check('''#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <stdio.h>
#include <inttypes.h>
#define QEMU_CLOCK_VIRTUAL 0
typedef struct {bool pending;int64_t deadline;} Timer;
typedef struct {struct {uint64_t pc,xregs[31];} env;} CPU;
static CPU *current_cpu;
#define ARM_CPU(c) ((CPU*)(c))
static int64_t now=100;
static int64_t qemu_clock_get_ns(int clock){(void)clock;return now;}
static bool timer_pending(Timer*t){return t->pending;}
static void timer_mod(Timer*t,int64_t deadline){t->pending=true;t->deadline=deadline;}
static void timer_del(Timer*t){t->pending=false;}
typedef struct {
 bool event1508_timing_model,event1508_aux_model,event1508_channel_model;
 bool z8_sensor_vd,z8_sensor_started,event_timing_active;
 bool primary_d980_prepared,primary_d980_live_single_model;
 uint64_t event_timing_period_ns,primary_d980_prepare_cancelled;
 uint32_t engine150c_active,engine150c_stop_requested,event_control_1508[4];
 Timer *event_timing_timer;
} NikonZ8State;
'''+production+'''
int main(void) {
 Timer timer={0};NikonZ8State s={0};s.event_timing_timer=&timer;
 s.event1508_timing_model=s.event1508_aux_model=s.event1508_channel_model=true;
 s.z8_sensor_vd=s.z8_sensor_started=true;s.event_timing_period_ns=33;
 s.event_control_1508[3]=1;s.primary_d980_prepared=true;
 event_timing_update(&s);assert(!timer.pending);
 /* Original reset retired the owner; its later START is the new clock edge. */
 s.engine150c_active=2;event_timing_update(&s);
 assert(timer.pending&&timer.deadline==133&&!s.event_timing_active);
 assert(s.event_control_1508[0]==0&&s.primary_d980_prepared&&!s.primary_d980_prepare_cancelled);
 now=110;event_timing_update(&s);assert(timer.deadline==133);
 s.engine150c_stop_requested=2;event_timing_update(&s);assert(!timer.pending);
 s.engine150c_stop_requested=0;event_timing_update(&s);assert(timer.pending&&timer.deadline==143);
 s.event_control_1508[3]=0;event_timing_update(&s);assert(!timer.pending);
 s.event_control_1508[3]=1;s.event_timing_period_ns=0;event_timing_update(&s);assert(!timer.pending);
 s.event_timing_timer=0;event_timing_update(&s);
 return 0;
}
''')
