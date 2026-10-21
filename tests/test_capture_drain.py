#!/usr/bin/env python3
# Copyright (C) 2026 RdWing: Z8 adaptation.
"""Check production drain readiness, IRQ masking and acknowledgement in C."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from source_helpers import ROOT, function

class CaptureDrain(unittest.TestCase):
    def test_primary_stop_contract(self):
        source = (ROOT/'qemu/nikon-z8-lab.c').read_text()
        names = ['primary_capture_drain_ready', 'primary_capture_drain_ack',
                 'engine150c_stop_read', 'engine150c_stop_irq_update']
        production = '\n'.join(function(source, n) for n in names)
        declarations = r'''
#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
typedef uint64_t hwaddr;
typedef struct {
 bool z8_still,primary_capture_direct_stop_model,primary_d980_single_armed;
 bool engine150c_stop_model,engine150d_control_model;
 uint32_t primary_reset_stage,engine150c_active,primary_capture_drain_pending;
 uint64_t primary_capture_drain_acks,primary_d980_single_frames;
 uint64_t primary_d980_single_epoch,primary_d980_input_epoch;
 uint32_t engine150c_stop_pending,engine150c_stop_done;
 uint32_t engine150c_direct_stop_pending,engine150c_direct_stop_pending1;
 uint32_t primary_empty_end_pending,engine150c_bit2_pending,engine150c_bit6_pending;
 uint32_t primary_capture_command_pending,video_primary_boundaries_pending;
 uint32_t statistics_pending,raw_primary_pending,raw_source_pending,primary_d980_pending;
 uint32_t engine_150c_init[0x224/4];
 int engine150c_irq;
} NikonZ8State;
static int irq;
static void qemu_set_irq(int line,int level){(void)line;irq=level;}
static void statistics_update(NikonZ8State*s){(void)s;}
static void primary_empty_end_update(NikonZ8State*s){(void)s;}
'''
        checks = r'''
int main(void){
 NikonZ8State s={.z8_still=true,.primary_capture_direct_stop_model=true,
  .engine150c_stop_model=true,.engine150c_active=0x401e,
  .primary_d980_single_frames=1,.primary_d980_single_epoch=7,
  .primary_d980_input_epoch=7};
 assert(primary_capture_drain_ready(&s,0x401e));
 assert(!primary_capture_drain_ready(&s,0x4000));
 s.primary_d980_single_armed=true;assert(!primary_capture_drain_ready(&s,0x401e));
 s.primary_d980_single_armed=false;s.primary_d980_input_epoch++;
 assert(!primary_capture_drain_ready(&s,0x401e));s.primary_d980_input_epoch--;
 s.primary_reset_stage=1;assert(!primary_capture_drain_ready(&s,0x401e));s.primary_reset_stage=0;
 s.engine150c_active=0x4000;assert(!primary_capture_drain_ready(&s,0x401e));s.engine150c_active=0x401e;
 s.primary_d980_single_frames=0;assert(!primary_capture_drain_ready(&s,0x401e));s.primary_d980_single_frames=1;
 s.primary_d980_single_epoch=0;assert(!primary_capture_drain_ready(&s,0x401e));s.primary_d980_single_epoch=7;
 s.z8_still=false;assert(!primary_capture_drain_ready(&s,0x401e));s.z8_still=true;
 s.primary_capture_direct_stop_model=false;assert(!primary_capture_drain_ready(&s,0x401e));
 uint64_t v=0;
 s.primary_capture_drain_pending=0x400;s.engine150c_bit6_pending=0x40;
 engine150c_stop_irq_update(&s);assert(!irq);
 assert(engine150c_stop_read(&s,0x150c0208,4,&v)&&v==0x440);
 assert(engine150c_stop_read(&s,0x150c0204,4,&v)&&v==0);
 s.engine_150c_init[0x200/4]=0x400;
 engine150c_stop_irq_update(&s);assert(irq);
 assert(engine150c_stop_read(&s,0x150c0204,4,&v)&&v==0x400);
 primary_capture_drain_ack(&s,0x40);assert(s.primary_capture_drain_pending==0x400);
 primary_capture_drain_ack(&s,0x400);engine150c_stop_irq_update(&s);
 assert(!irq&&s.primary_capture_drain_acks==1&&s.engine150c_bit6_pending==0x40);
 primary_capture_drain_ack(&s,0x400);assert(s.primary_capture_drain_acks==1);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'test.c').write_text(declarations+production+checks)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(p/'test.c'),'-o',str(p/'test')],check=True)
            subprocess.run([str(p/'test')],check=True)

class PreviewDrain(unittest.TestCase):
    def test_active_preview_stop_not_frame_or_idle_stop(self):
        source = (ROOT/'qemu/nikon-z8-lab.c').read_text()
        production = function(source, 'engine1543_control_write')
        declarations = r"""
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <inttypes.h>
#include <assert.h>
typedef uint64_t hwaddr;
typedef struct {
 bool z8_still,capture_nv16_model,raw_pipeline_model;
 bool engine1543_video_program_known,video_raw_transport_model,video_raw_ring_latched;
 uint64_t capture_stream_rearms,engine1543_retained_starts;
 bool engine1543_held[3],engine1543_active[3];
 uint32_t engine1542_config[13][0x600/4],engine1543_latched[3][0x600/4];
 uint32_t engine1543_valid[3],engine1542_pending[13];
 uint64_t engine1543_starts[3],engine1543_stops[3],engine1543_holds[3];
 unsigned raw_pipeline_row,raw_pipeline_bank;
 bool raw_pipeline_wait_bank,raw_pipeline_refill_notified;
} NikonZ8State;
typedef struct{int cpu_index;struct{uint64_t pc;}env;} CPU;
static CPU *current_cpu;
#define ARM_CPU(x) (x)
static uint32_t engine1542_bases[13];
static unsigned irq_updates,invalid;
static bool engine1543_video_ready(NikonZ8State*s,unsigned j){(void)s;(void)j;return false;}
static bool engine1543_retained_video_start(NikonZ8State*s,unsigned j,uint64_t v){(void)s;(void)j;(void)v;return false;}
static bool capture_stream_can_rearm(NikonZ8State*s,unsigned j){(void)s;(void)j;return false;}
static bool engine1543_ready(NikonZ8State*s,unsigned j){(void)s;(void)j;return true;}
static bool capture_nv16_prepare(NikonZ8State*s){(void)s;return true;}
static void capture_nv16_cancel(NikonZ8State*s){(void)s;}
static void capture_nv16_try(NikonZ8State*s){(void)s;}
static void raw_pipeline_irq_update(NikonZ8State*s){(void)s;irq_updates++;}
static void unknown_access(NikonZ8State*s,hwaddr a,uint64_t v,unsigned z,bool w){
 (void)s;(void)a;(void)v;(void)z;(void)w;invalid++;
}
"""
        checks = r"""
int main(void){
 NikonZ8State s={.z8_still=true,.engine1543_active={true,false,false}};
 assert(engine1543_control_write(&s,10,0x15431004,0x100));
 assert(!s.engine1543_active[0]&&!s.engine1543_held[0]);
 assert(s.engine1542_pending[10]==0x20&&s.engine1543_stops[0]==1&&irq_updates==1);
 assert(!(s.engine1542_pending[10]&9)); /* no fabricated frame/refill */
 s.engine1542_pending[10]=0;
 engine1543_control_write(&s,10,0x15431004,0x100);
 assert(!s.engine1542_pending[10]&&s.engine1543_stops[0]==1&&irq_updates==1);
 engine1543_control_write(&s,10,0x15431004,0x101);
 engine1543_control_write(&s,10,0x15431004,0x102);
 assert(s.engine1543_held[0]&&!s.engine1542_pending[10]);
 engine1543_control_write(&s,10,0x15431004,0x100);
 assert(s.engine1542_pending[10]==0x20&&s.engine1543_stops[0]==2&&irq_updates==2);
 s.engine1542_pending[10]=0;s.engine1543_active[0]=true;s.z8_still=false;
 engine1543_control_write(&s,10,0x15431004,0x100);
 assert(!s.engine1542_pending[10]&&irq_updates==2);
 s.z8_still=true;s.engine1543_active[1]=true;
 engine1543_control_write(&s,11,0x15432004,0x100);
 assert(!s.engine1542_pending[11]&&irq_updates==2); /* preview scope only */
 engine1543_control_write(&s,10,0x15431004,0x200);
 assert(invalid==1);
 return 0;
}
"""
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'test.c').write_text(declarations+production+checks)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(p/'test.c'),'-o',str(p/'test')],check=True)
            subprocess.run([str(p/'test')],check=True,capture_output=True)

if __name__=='__main__':unittest.main()
