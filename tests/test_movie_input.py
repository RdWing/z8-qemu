# Copyright (C) 2026 RdWing: Z8 adaptation.
"""Movie control ownership and the Z8 finite/continuous input boundary."""
import unittest
from test_shared221 import SOURCE, check
from source_helpers import function


class MovieInput(unittest.TestCase):
    def test_video_domain_command_poll_and_rejection(self):
        source = (SOURCE / 'nikon-z8-lab.c').read_text()
        check(r'''
#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
typedef uint64_t hwaddr;
typedef struct {
 bool video_peripheral_control_model,bootstrap_fixtures,video_peripheral_pending;
 uint32_t video_peripheral_selection,video_peripheral_latched;
 uint64_t video_peripheral_commands,video_peripheral_polls;
} NikonZ8State;
static unsigned rejects;
static void unknown_access(NikonZ8State*s,hwaddr a,uint64_t v,unsigned n,bool w)
{(void)s;(void)a;(void)v;(void)n;(void)w;rejects++;}
''' + function(source, 'video_peripheral_access') + r'''
int main(void) {
 NikonZ8State s={.video_peripheral_control_model=true,.bootstrap_fixtures=true};
 uint64_t v=1;
 assert(video_peripheral_access(&s,0x0d154030,&v,4,true));
 assert(rejects==1&&!s.video_peripheral_pending);
 v=7;assert(video_peripheral_access(&s,0x0d154150,&v,4,true));
 v=1;assert(video_peripheral_access(&s,0x0d154030,&v,4,true));
 assert(s.video_peripheral_latched==7&&s.video_peripheral_commands==1);
 v=3;assert(video_peripheral_access(&s,0x0d154150,&v,4,true));
 assert(rejects==2&&s.video_peripheral_selection==7);
 assert(video_peripheral_access(&s,0x0d154030,&v,4,false)&&v==1);
 assert(video_peripheral_access(&s,0x0d154030,&v,4,false)&&v==0);
 v=3;assert(video_peripheral_access(&s,0x0d154150,&v,4,true));
 v=1;assert(video_peripheral_access(&s,0x0d154030,&v,4,true));
 assert(s.video_peripheral_latched==3&&s.video_peripheral_commands==2);
 v=2;assert(video_peripheral_access(&s,0x0d154150,&v,4,true));
 assert(rejects==3&&s.video_peripheral_selection==3);
 assert(video_peripheral_access(&s,0x0d154030,&v,2,false));assert(rejects==4);
 assert(!video_peripheral_access(&s,0x0d154044,&v,4,false));
 s.video_peripheral_control_model=false;
 assert(!video_peripheral_access(&s,0x0d154030,&v,4,false));
 return 0;
}
''')

    def test_z8_fifo_selection_requires_valid_raw_program(self):
        source = (SOURCE / 'nikon-z8-pixels.h').read_text()
        check(r'''
#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
typedef struct { bool z8_realized,valid; uint32_t engine1542_config[2][2]; } NikonZ8State;
static bool video_raw_descriptor(NikonZ8State*s) { return s->valid; }
''' + function(source, 'video_supplier_selected') + r'''
int main(void) {
 NikonZ8State s={0};s.engine1542_config[1][1]=2;
 assert(!video_supplier_selected(&s));s.z8_realized=true;
 assert(!video_supplier_selected(&s));s.valid=true;
 assert(video_supplier_selected(&s));s.engine1542_config[1][1]=0;
 assert(!video_supplier_selected(&s));s.engine1542_config[1][1]=0x202;
 s.z8_realized=false;s.valid=false;assert(video_supplier_selected(&s));
 return 0;
}
''')

    def test_movie_clock_preserves_finite_still_owner(self):
        source = (SOURCE / 'nikon-z8-d980.h').read_text()
        check(r'''
#include <stdbool.h>
#include <assert.h>
#include <stdio.h>
#include <inttypes.h>
typedef struct { bool z8_timed_single_model,primary_d980_single_armed; uint32_t event_control_1508[4]; uint64_t primary_d980_frames,primary_d980_bytes,primary_d980_single_epoch; bool z8_still,video,finite; unsigned receives; } NikonZ8State;
static void primary_d980_single_complete(NikonZ8State*s){(void)s;}
static bool video_raw_descriptor(NikonZ8State*s) { return s->video; }
static bool primary_d980_finite_input_owned(NikonZ8State*s) { return s->finite; }
static bool primary_d980_receive(NikonZ8State*s,bool single)
{ assert(!single);s->receives++;return true; }
''' + function(source, 'primary_d980_tick') + r'''
int main(void) {
 NikonZ8State s={.z8_still=true};
 primary_d980_tick(&s);assert(!s.receives);
 s.video=true;primary_d980_tick(&s);assert(s.receives==1);
 s.finite=true;primary_d980_tick(&s);assert(s.receives==1);
 s.video=false;s.z8_still=false;primary_d980_tick(&s);assert(s.receives==1);
 s.finite=false;primary_d980_tick(&s);assert(s.receives==2);
 return 0;
}
''')

if __name__ == '__main__':
    unittest.main()
