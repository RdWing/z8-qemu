# SPDX-License-Identifier: GPL-2.0-or-later
"""Finite RAW ownership and the photo frame clock have different lifetimes."""
from pathlib import Path
import unittest
from source_helpers import function
from test_shared221 import check


class FiniteChannelClock(unittest.TestCase):
    def test_clock_waits_for_this_exposure_without_releasing_raw_ownership(self):
        source = (Path(__file__).resolve().parents[1] / 'qemu/nikon-z8-lab.c').read_text()
        production = '\n'.join(function(source, name) for name in
                               ['primary_d980_finite_input_owned',
                                'primary_d980_channel_clock_ready'])
        check('''#include <stdint.h>
#include <stdbool.h>
#include <assert.h>
#include <string.h>
typedef struct {
 bool primary_d980_live_single_model,primary_d980_single_model;
 bool primary_d980_single_armed,engine150c_stop_reset_asserted;
 uint32_t engine150c_active,primary_reset_stage,engine150c_stop_requested;
 uint64_t primary_d980_single_frames,primary_d980_single_epoch,primary_d980_input_epoch;
} NikonZ8State;
static bool video;
static bool video_raw_descriptor(NikonZ8State *s){(void)s;return video;}
''' + production + '''
int main(void){
 NikonZ8State s={0};
 assert(primary_d980_channel_clock_ready(&s));
 s.primary_d980_live_single_model=s.primary_d980_single_model=true;
 s.engine150c_active=0x4000;s.primary_d980_input_epoch=7;
 assert(primary_d980_finite_input_owned(&s));
 assert(!primary_d980_channel_clock_ready(&s));
 s.primary_d980_single_frames=1;s.primary_d980_single_epoch=7;
 NikonZ8State before=s;
 for(int i=0;i<20;i++){
  assert(primary_d980_channel_clock_ready(&s));
  assert(primary_d980_finite_input_owned(&s));
 }
 assert(!memcmp(&s,&before,sizeof(s)));
 s.primary_d980_input_epoch=8;assert(!primary_d980_channel_clock_ready(&s));
 s.primary_d980_input_epoch=7;s.primary_d980_single_epoch=0;
 assert(!primary_d980_channel_clock_ready(&s));s.primary_d980_single_epoch=7;
 s.primary_d980_single_armed=true;assert(!primary_d980_channel_clock_ready(&s));
 s.primary_d980_single_armed=false;s.primary_reset_stage=1;
 assert(!primary_d980_channel_clock_ready(&s));s.primary_reset_stage=0;
 s.engine150c_stop_requested=0x4000;assert(!primary_d980_channel_clock_ready(&s));
 s.engine150c_stop_requested=0;s.engine150c_stop_reset_asserted=true;
 assert(!primary_d980_channel_clock_ready(&s));s.engine150c_stop_reset_asserted=false;
 video=true;assert(primary_d980_channel_clock_ready(&s));
 assert(!primary_d980_finite_input_owned(&s));
 return 0;
}
''')
