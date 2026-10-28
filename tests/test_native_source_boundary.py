# SPDX-License-Identifier: GPL-2.0-or-later
"""Capture-pad source timing does not own pixel DMA or native IRQ retirement."""
from pathlib import Path
import unittest
from source_helpers import function
from test_shared221 import check


class NativeSourceBoundary(unittest.TestCase):
    def test_masked_pad_and_complete_source_frame(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / 'qemu/nikon-z8-pixels.h').read_text()
        production = '\n'.join(function(source, name) for name in
                               ['raw_pipeline_source_pad_write',
                                'raw_pipeline_source_boundary_ready'])
        check('''#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <string.h>
typedef struct {
 bool native_mcu,z8_still,z8_timed_single_model,engine152c_he_still_model;
 bool raw_pipeline_source_gate_held;
 uint32_t raw_pipeline_source_pad;
 uint64_t raw_pipeline_source_deferred_frames;
 uint64_t pixel_bytes,he_jobs,irq_acks;
 uint64_t primary_d980_single_frames,engine152c_he_jobs,engine152c_he_acks,engine152c_he_stop_acks;
 bool engine152c_he_pending,engine152c_he_stop_pending;
 uint32_t event_global1_pending;
} NikonZ8State;
static bool owner;
static bool primary_d980_finite_input_owned(NikonZ8State *s){(void)s;return owner;}
''' + production + '''
int main(void){
 NikonZ8State s={0};
 raw_pipeline_source_pad_write(&s,0x00800080);
 assert(s.raw_pipeline_source_pad==0x80);
 raw_pipeline_source_pad_write(&s,0x00010001);
 assert(s.raw_pipeline_source_pad==0x81);
 raw_pipeline_source_pad_write(&s,0x00000000);
 raw_pipeline_source_pad_write(&s,0x00000080);
 assert(s.raw_pipeline_source_pad==0x81);
 assert(raw_pipeline_source_boundary_ready(&s));
 owner=true;s.native_mcu=s.z8_still=s.z8_timed_single_model=s.engine152c_he_still_model=true;
 s.pixel_bytes=123456;s.event_global1_pending=0x10;s.irq_acks=23;
 for(unsigned capture=0;capture<4;capture++){
  s.he_jobs=capture; /* The envelope owns the boundary before HE starts too. */
  s.primary_d980_single_frames=s.engine152c_he_jobs=s.engine152c_he_acks=s.engine152c_he_stop_acks=capture;
  raw_pipeline_source_pad_write(&s,0x00800080);
  uint64_t deferred=s.raw_pipeline_source_deferred_frames;
  for(unsigned frame=0;frame<3;frame++) assert(!raw_pipeline_source_boundary_ready(&s));
  assert(s.raw_pipeline_source_gate_held);
  raw_pipeline_source_pad_write(&s,0x00010000); /* An unrelated pin cannot release it. */
  assert(s.raw_pipeline_source_pad==0x80);
  raw_pipeline_source_pad_write(&s,0x00800000);
  assert(!raw_pipeline_source_boundary_ready(&s)); /* First edge starts an ungated frame. */
  assert(!s.raw_pipeline_source_gate_held);
  assert(s.raw_pipeline_source_deferred_frames==deferred+4);
  for(unsigned frame=0;frame<3;frame++) assert(raw_pipeline_source_boundary_ready(&s));
  assert(s.pixel_bytes==123456 && s.event_global1_pending==0x10 && s.irq_acks==23);
 }
 /* A short pad assertion between output ticks still invalidates that frame. */
 raw_pipeline_source_pad_write(&s,0x00800080);
 raw_pipeline_source_pad_write(&s,0x00800000);
 assert(!raw_pipeline_source_boundary_ready(&s));
 assert(raw_pipeline_source_boundary_ready(&s));
 s.primary_d980_single_frames++;
 assert(!raw_pipeline_source_boundary_ready(&s));
 s.engine152c_he_jobs++;s.engine152c_he_acks++;
 assert(!raw_pipeline_source_boundary_ready(&s));
 s.engine152c_he_stop_acks++;
 assert(!raw_pipeline_source_boundary_ready(&s));
 assert(raw_pipeline_source_boundary_ready(&s));
 for(unsigned pending=0;pending<2;pending++){
  bool *field=pending?&s.engine152c_he_stop_pending:&s.engine152c_he_pending;
  *field=true;assert(!raw_pipeline_source_boundary_ready(&s));
  *field=false;assert(!raw_pipeline_source_boundary_ready(&s));
  assert(raw_pipeline_source_boundary_ready(&s));
 }
 raw_pipeline_source_pad_write(&s,0x00800080);
 assert(!raw_pipeline_source_boundary_ready(&s));
 uint64_t deferred=s.raw_pipeline_source_deferred_frames;
 owner=false;assert(raw_pipeline_source_boundary_ready(&s));
 assert(!s.raw_pipeline_source_gate_held && s.raw_pipeline_source_deferred_frames==deferred);
 owner=true;
 bool *profiles[]={&s.native_mcu,&s.z8_still,&s.z8_timed_single_model,&s.engine152c_he_still_model};
 for(unsigned i=0;i<4;i++){
  *profiles[i]=false;s.raw_pipeline_source_gate_held=true;
  assert(raw_pipeline_source_boundary_ready(&s));
  assert(!s.raw_pipeline_source_gate_held && s.raw_pipeline_source_deferred_frames==deferred);
  *profiles[i]=true;
 }
 assert(s.pixel_bytes==123456 && s.event_global1_pending==0x10 && s.irq_acks==23);
 return 0;
}
''')

    def test_source_retirement_owns_its_completed_he_transaction(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / 'qemu/nikon-z8-lab.c').read_text()
        production = function(source, 'primary_d980_live_source_retired')
        check('''#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
typedef struct {
 bool native_mcu,z8_still,z8_timed_single_model,engine152c_he_still_model;
 bool primary_d980_prepared,engine152c_he_pending,engine152c_request_pending;
 bool engine152c_he_stop_pending,engine152c_stream_requested;
 uint32_t engine152c_stream_pending;
 uint64_t engine152c_he_jobs,primary_d980_single_frames;
 uint64_t engine152c_he_acks,engine152c_he_stop_acks;
} NikonZ8State;
static bool owner=true,clock_ready=true;
static bool primary_d980_finite_input_owned(NikonZ8State *s){(void)s;return owner;}
static bool primary_d980_channel_clock_ready(NikonZ8State *s){(void)s;return clock_ready;}
''' + production + '''
int main(void){
 NikonZ8State s={.native_mcu=true,.z8_still=true,.z8_timed_single_model=true,.engine152c_he_still_model=true,
  .engine152c_he_jobs=1,.primary_d980_single_frames=1,.engine152c_he_acks=1,.engine152c_he_stop_acks=1};
 assert(primary_d980_live_source_retired(&s));
 owner=false;assert(!primary_d980_live_source_retired(&s));owner=true;
 clock_ready=false;assert(!primary_d980_live_source_retired(&s));clock_ready=true;
 bool *profiles[]={&s.native_mcu,&s.z8_still,&s.z8_timed_single_model,&s.engine152c_he_still_model};
 for(unsigned i=0;i<4;i++){*profiles[i]=false;assert(!primary_d980_live_source_retired(&s));*profiles[i]=true;}
 bool *busy[]={&s.primary_d980_prepared,&s.engine152c_he_pending,&s.engine152c_request_pending,
  &s.engine152c_he_stop_pending,&s.engine152c_stream_requested};
 for(unsigned i=0;i<5;i++){*busy[i]=true;assert(!primary_d980_live_source_retired(&s));*busy[i]=false;}
 s.engine152c_stream_pending=4;assert(!primary_d980_live_source_retired(&s));s.engine152c_stream_pending=0;
 s.primary_d980_single_frames=2;assert(!primary_d980_live_source_retired(&s));
 s.engine152c_he_jobs=2;assert(!primary_d980_live_source_retired(&s));
 s.engine152c_he_acks=2;assert(!primary_d980_live_source_retired(&s));
 s.engine152c_he_stop_acks=2;assert(primary_d980_live_source_retired(&s));
 return 0;
}
''')

    def test_idle_held_supplier_requires_retired_current_photo(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / 'qemu/nikon-z8-lab.c').read_text()
        production = '\n'.join(function(source, name) for name in
                               ['primary_live_photo_held_supplier',
                                'primary_live_photo_writer_reset_mask',
                                'primary_live_photo_reset_writer'])
        check('''#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
typedef struct {
 bool native_mcu,z8_still,z8_timed_single_model,engine152c_he_still_model;
 bool engine1543_active[2],engine1543_held[2];
 bool primary_d980_single_armed,primary_d980_prepared;
 bool engine152c_he_pending,engine152c_request_pending,engine152c_he_stop_pending,engine152c_stream_requested;
 uint32_t primary_reset_stage,engine150c_active,engine150c_stop_requested,engine_150c_init[0x220/4],engine152c_stream_pending,primary_d980_pending;
 uint64_t primary_d980_single_frames,primary_d980_single_epoch,primary_d980_input_epoch;
 uint64_t primary_d980_cancelled,primary_d980_acks;
 uint64_t engine152c_he_jobs,engine152c_he_acks,engine152c_he_stop_acks;
} NikonZ8State;
static bool owner=true;
static bool primary_d980_finite_input_owned(NikonZ8State *s){(void)s;return owner;}
''' + production + '''
int main(void){
 NikonZ8State s={.native_mcu=true,.z8_still=true,.z8_timed_single_model=true,.engine152c_he_still_model=true,
  .engine1543_active={false,true},.engine1543_held={false,true},.engine150c_active=0x77f7f,.engine150c_stop_requested=0x400e,
  .primary_d980_single_frames=2,.primary_d980_single_epoch=2,.primary_d980_input_epoch=2,
  .engine152c_he_jobs=2,.engine152c_he_acks=2,.engine152c_he_stop_acks=2};
 s.engine_150c_init[0x18/4]=0x400e;
 assert(primary_live_photo_held_supplier(&s,0x400e));
 for(unsigned units=0;units<=0x401e;units++) if(units!=0x400e) assert(!primary_live_photo_held_supplier(&s,units));
 owner=false;assert(!primary_live_photo_held_supplier(&s,0x400e));owner=true;
 bool *profiles[]={&s.native_mcu,&s.z8_still,&s.z8_timed_single_model,&s.engine152c_he_still_model,&s.engine1543_active[1],&s.engine1543_held[1]};
 for(unsigned i=0;i<6;i++){*profiles[i]=false;assert(!primary_live_photo_held_supplier(&s,0x400e));*profiles[i]=true;}
 bool *busy[]={&s.primary_d980_single_armed,&s.primary_d980_prepared,&s.engine152c_he_pending,&s.engine152c_request_pending,&s.engine152c_he_stop_pending,&s.engine152c_stream_requested};
 for(unsigned i=0;i<6;i++){*busy[i]=true;assert(!primary_live_photo_held_supplier(&s,0x400e));*busy[i]=false;}
 uint32_t *required[]={&s.engine150c_active,&s.engine150c_stop_requested,&s.engine_150c_init[0x18/4]};
 for(unsigned i=0;i<3;i++) for(unsigned bit=1;bit;bit<<=1){if(!(bit&0x400e))continue;uint32_t saved=*required[i];*required[i]&=~bit;assert(!primary_live_photo_held_supplier(&s,0x400e));*required[i]=saved;}
 s.primary_reset_stage=1;assert(!primary_live_photo_held_supplier(&s,0x400e));s.primary_reset_stage=0;
 s.engine152c_stream_pending=4;assert(!primary_live_photo_held_supplier(&s,0x400e));s.engine152c_stream_pending=0;
 uint64_t *counts[]={&s.primary_d980_single_frames,&s.engine152c_he_jobs,&s.engine152c_he_acks,&s.engine152c_he_stop_acks,&s.primary_d980_single_epoch,&s.primary_d980_input_epoch};
 for(unsigned i=0;i<6;i++){(*counts[i])--;assert(!primary_live_photo_held_supplier(&s,0x400e));(*counts[i])++;}
 s.primary_d980_single_epoch=s.primary_d980_input_epoch=0;assert(!primary_live_photo_held_supplier(&s,0x400e));
 s.primary_d980_pending=0x04000000;
 assert(!primary_live_photo_writer_reset_mask(&s,0x400e));
 primary_live_photo_reset_writer(&s,0x400e);assert(s.primary_d980_pending==0x04000000);
 s.primary_d980_single_epoch=s.primary_d980_input_epoch=2;s.primary_d980_acks=7;
 assert(primary_live_photo_writer_reset_mask(&s,0x400e)==0x04000000);
 assert(s.primary_d980_pending==0x04000000 && !s.primary_d980_cancelled);
 primary_live_photo_reset_writer(&s,0x400e);
 assert(!s.primary_d980_pending && s.primary_d980_cancelled==1 && s.primary_d980_acks==7);
 primary_live_photo_reset_writer(&s,0x400e);assert(s.primary_d980_cancelled==1);
 s.primary_d980_pending=0x04000000;s.engine_150c_init[0x20c/4]=0x04000000;
 primary_live_photo_reset_writer(&s,0x400e);assert(s.primary_d980_pending==0x04000000 && s.primary_d980_cancelled==1);
 s.engine_150c_init[0x20c/4]=0;s.primary_d980_pending|=1;
 primary_live_photo_reset_writer(&s,0x400e);assert(s.primary_d980_pending==0x04000001 && s.primary_d980_cancelled==1);
 s.primary_d980_pending=0x04000000;s.primary_d980_single_armed=true;
 primary_live_photo_reset_writer(&s,0x400e);assert(s.primary_d980_pending==0x04000000 && s.primary_d980_cancelled==1);
 s.primary_d980_single_armed=false;
 primary_live_photo_reset_writer(&s,0x401e);assert(s.primary_d980_pending==0x04000000 && s.primary_d980_cancelled==1);
 return 0;
}
''')
