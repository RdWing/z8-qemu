# Copyright (C) 2026 RdWing: Z8 adaptation.
"""Native movie reset may cancel only its own masked statistics result."""
import unittest
from test_shared221 import SOURCE, check
from source_helpers import function


class MovieExit(unittest.TestCase):
    def test_reset_retains_unrelated_pending_owners(self):
        source = (SOURCE / 'nikon-z8-lab.c').read_text()
        production = '\n'.join(function(source, name) for name in
                               ['video_reset_discards_statistics', 'primary_live_photo_writer_reset_mask',
                                'video_forced_stop_quiescent'])
        check(r'''
#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
typedef struct {
 bool z8_realized,video_forced_stop_model,video_raw_transport_model,event_timing_active;
 unsigned primary_reset_stage;
 uint32_t statistics_pending,engine150c_stop_requested,engine_150c_init[0x220/4];
 bool engine1543_active[2],packet_owned;
 uint32_t engine152c_stream_pending,engine1530_config[0x20/4];
 uint32_t engine1542_pending[12],raw_primary_pending,raw_source_pending;
 uint32_t primary_d980_pending,engine151_pending[2],event_global1_pending;
 struct { uint32_t pending; } engine1518[1];
} NikonZ8State;
static bool video_raw_packet_blocks_producer(NikonZ8State*s) { return s->packet_owned; }
static bool held_photo;
static bool primary_live_photo_held_supplier(NikonZ8State*s,uint32_t units){(void)s;return held_photo && units==0x400e;}
''' + production + r'''
int main(void) {
 NikonZ8State s={.z8_realized=true,.video_forced_stop_model=true,
   .video_raw_transport_model=true,.statistics_pending=0x20,
   .engine150c_stop_requested=0xf04f};
 s.engine_150c_init[0x18/4]=0x10f04f;
 assert(video_reset_discards_statistics(&s,0xf04f));
 assert(video_forced_stop_quiescent(&s,0xf04f));
 assert(s.statistics_pending==0x20); /* admission does not mutate ownership */
 assert(!video_forced_stop_quiescent(&s,0x4000));
 s.engine_150c_init[0x20c/4]=0x20;
 assert(!video_forced_stop_quiescent(&s,0xf04f));
 s.engine_150c_init[0x20c/4]=0;
 s.engine_150c_init[0x18/4]&=~8u;assert(!video_forced_stop_quiescent(&s,0xf04f));
 s.engine_150c_init[0x18/4]|=8;
 s.engine150c_stop_requested&=~8u;assert(!video_forced_stop_quiescent(&s,0xf04f));
 s.engine150c_stop_requested|=8;
 s.event_timing_active=true;assert(!video_forced_stop_quiescent(&s,0xf04f));
 s.event_timing_active=false;s.video_forced_stop_model=false;
 assert(!video_forced_stop_quiescent(&s,0xf04f));s.video_forced_stop_model=true;
 s.statistics_pending=0x60;assert(!video_forced_stop_quiescent(&s,0xf04f));
 s.statistics_pending=0x20;
 #define OWNER(expr) do { expr=1; assert(!video_forced_stop_quiescent(&s,0xf04f)); expr=0; } while(0)
 OWNER(s.packet_owned);OWNER(s.engine1543_active[1]);
 OWNER(s.engine152c_stream_pending);OWNER(s.raw_primary_pending);
 OWNER(s.raw_source_pending);OWNER(s.primary_d980_pending);
 OWNER(s.engine1542_pending[1]);OWNER(s.engine1542_pending[10]);OWNER(s.engine1542_pending[11]);
 s.engine1530_config[0x1c/4]=4;assert(!video_forced_stop_quiescent(&s,0xf04f));
 s.engine1530_config[0x1c/4]=0;s.engine151_pending[0]=8;
 assert(!video_forced_stop_quiescent(&s,0xf04f));s.engine151_pending[0]=0;
 s.engine1518[0].pending=0x08000000;assert(!video_forced_stop_quiescent(&s,0xf04f));
 s.engine1518[0].pending=0;s.event_global1_pending=0x10;
 assert(!video_forced_stop_quiescent(&s,0xf04f));
 s.event_global1_pending=0;
 /* The narrow held-Photo exception never releases a pending pixel/IRQ owner. */
 s.statistics_pending=0;s.engine1543_active[1]=true;held_photo=true;
 assert(video_forced_stop_quiescent(&s,0x400e));
 assert(!video_forced_stop_quiescent(&s,0x401e));
 #define PHOTO_OWNER(expr) do { expr=1; assert(!video_forced_stop_quiescent(&s,0x400e)); expr=0; } while(0)
 PHOTO_OWNER(s.packet_owned);PHOTO_OWNER(s.engine152c_stream_pending);
 PHOTO_OWNER(s.raw_primary_pending);PHOTO_OWNER(s.raw_source_pending);
 PHOTO_OWNER(s.primary_d980_pending);
 s.primary_d980_pending=0x04000000;
 assert(video_forced_stop_quiescent(&s,0x400e));assert(s.primary_d980_pending==0x04000000);
 s.engine_150c_init[0x20c/4]=0x04000000;assert(!video_forced_stop_quiescent(&s,0x400e));
 s.engine_150c_init[0x20c/4]=0;s.primary_d980_pending|=1;
 assert(!video_forced_stop_quiescent(&s,0x400e));s.primary_d980_pending=0;
 PHOTO_OWNER(s.engine1542_pending[1]);
 PHOTO_OWNER(s.engine1542_pending[10]);PHOTO_OWNER(s.engine1542_pending[11]);
 s.engine151_pending[0]=8;assert(!video_forced_stop_quiescent(&s,0x400e));s.engine151_pending[0]=0;
 s.engine1518[0].pending=0x08000000;assert(!video_forced_stop_quiescent(&s,0x400e));s.engine1518[0].pending=0;
 s.event_global1_pending=0x10;assert(!video_forced_stop_quiescent(&s,0x400e));s.event_global1_pending=0;
 s.statistics_pending=0x20;assert(video_forced_stop_quiescent(&s,0x400e));
 assert(s.statistics_pending==0x20); /* Existing masked-statistics reset policy is unchanged. */
 s.event_timing_active=true;assert(!video_forced_stop_quiescent(&s,0x400e));s.event_timing_active=false;
 s.statistics_pending=0x60;assert(!video_forced_stop_quiescent(&s,0x400e));s.statistics_pending=0;
 held_photo=false;s.engine1543_active[1]=false;
 s.primary_reset_stage=1;
 assert(!video_forced_stop_quiescent(&s,0xf04f));
 return 0;
}
''')

if __name__ == '__main__':
    unittest.main()
