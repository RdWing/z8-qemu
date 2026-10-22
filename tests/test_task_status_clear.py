# Copyright (C) 2026 RdWing: Z8 adaptation.
"""Native Z8 task status clearing and command ownership, without firmware."""
import unittest
from test_shared221 import SOURCE, check
from source_helpers import function


class TaskStatusClear(unittest.TestCase):
    def test_native_clear_start_stop_and_rejection(self):
        source = (SOURCE / 'nikon-z8-lab.c').read_text()
        production = '\n'.join(function(source, n) for n in
                               ['task1500_status_address', 'task1500_control_write'])
        check(r'''
#include <stdbool.h>
#include <stdint.h>
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <inttypes.h>
typedef uint64_t hwaddr;
#define HWADDR_PRIx PRIx64
#define OBJECT(s) (s)
#define MACHINE_TYPE_NAME(s) (s)
#define ARM_CPU(s) (s)
static struct { int cpu_index; struct { uint64_t pc; } env; } *current_cpu;
typedef struct {
 bool bootstrap_fixtures,task1500_control_model,task1500_ff_clear_model,zr;
 uint32_t task1500_status_clear_seen,task1500_active,task1500_arm_seen,engine_1500_init;
 uint64_t task1500_status_clears,task1500_ack_writes,task1500_starts,task1500_stops;
 uint32_t task1500_latched[32][20],task_1500_desc[32][20];
} NikonZ8State;
static void *object_dynamic_cast(NikonZ8State *s,const char *name)
{ (void)name; return s->zr ? s : NULL; }
static uint32_t task1500_ready_mask(NikonZ8State *s) { (void)s; return 4; }
static unsigned ctz32(uint32_t v) { return __builtin_ctz(v); }
static unsigned misses;
static void unknown_access(NikonZ8State*s,hwaddr a,uint64_t v,unsigned n,bool w)
{ (void)s;(void)a;(void)v;(void)n;(void)w;misses++; }
''' + production + r'''
int main(void) {
 NikonZ8State s={.bootstrap_fixtures=true,.task1500_control_model=true,.task1500_ff_clear_model=true};
 #define WRITE(a,v) assert(task1500_control_write(&s,a,v,4))
 /* Native setup clears status, but a launch still requires a fresh arm. */
 WRITE(0x15000304,0xff);assert(s.task1500_status_clear_seen==4);
 WRITE(0x15000008,4);assert(misses==1&&!s.task1500_starts);
 WRITE(0x15000000,4);WRITE(0x15000004,4);
 WRITE(0x15000008,4);assert(misses==2&&!s.task1500_active);
 WRITE(0x15000304,0xff);s.task_1500_desc[2][7]=0x12345678;
 WRITE(0x15000008,4);
 assert(s.task1500_active==4&&s.task1500_starts==1);
 assert(s.task1500_latched[2][7]==0x12345678);
 s.task_1500_desc[2][7]=0;assert(s.task1500_latched[2][7]==0x12345678);
 WRITE(0x15000008,4);assert(misses==3&&s.task1500_starts==1);
 WRITE(0x1500000c,4);assert(!s.task1500_active&&s.task1500_stops==1);
 uint64_t clears=s.task1500_status_clears;
 WRITE(0x15000304,1);assert(misses==4&&s.task1500_status_clears==clears);
 assert(task1500_control_write(&s,0x15000304,0xff,2));assert(misses==5);
 s.task1500_ff_clear_model=false;WRITE(0x15000304,0xff);assert(misses==6);
 WRITE(0x15000304,0);assert(s.task1500_status_clears==clears+1);
 s.task1500_ff_clear_model=true;WRITE(0x15000304,0xff);assert(s.task1500_status_clears==clears+2);
 return 0;
}
''')


if __name__ == '__main__':
    unittest.main()
