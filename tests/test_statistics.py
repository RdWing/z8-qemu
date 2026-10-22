#!/usr/bin/env python3
# Copyright (C) 2026 RdWing: Z8 adaptation.
"""Execute the production statistics writer against guarded RAM, without firmware."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from source_helpers import ROOT, function

SOURCE = Path(os.environ.get('Z8_STATISTICS_SOURCE', ROOT/'qemu/nikon-z8-lab.c'))

class StatisticsDMA(unittest.TestCase):
    def test_record_counts_and_guards(self):
        source = SOURCE.read_text()
        source = source[source.index('static void statistics_tick(void *opaque)\n{'):]
        tick = function(source, 'statistics_tick')
        pre = r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <assert.h>
#include <inttypes.h>
#define BASE UINT64_C(0xa00001000)
#define BYTES (64*1536)
typedef struct {
 uint32_t config150d_latched[1024];
 uint16_t statistics_means[12][30];
 unsigned statistics_pending,statistics_last_records;
 uint64_t statistics_rejects,statistics_target,statistics_frames,statistics_bytes;
 uint64_t statistics_records,statistics_events;
 bool active;
} NikonZ8State;
static uint8_t ram[BYTES+64];
static unsigned irq_updates,retries,writes;
static size_t valid_bytes;
static bool statistics_active(NikonZ8State *s){return s->active;}
static void statistics_update(NikonZ8State *s){retries++;}
static void engine150c_stop_irq_update(NikonZ8State *s){irq_updates++;}
static bool dma_ram_range(NikonZ8State *s,uint64_t a,uint64_t n){
 return a>=BASE && n<=valid_bytes && a-BASE<=valid_bytes-n;
}
static void stw_le_p(void *p,uint16_t v){uint8_t *b=p;b[0]=v;b[1]=v>>8;}
static void cpu_physical_memory_write(uint64_t a,const void *p,size_t n){
 assert(a>=BASE && a-BASE+n<=valid_bytes);
 memcpy(ram+32+(a-BASE),p,n);writes++;
}
static NikonZ8State setup(unsigned records,unsigned bank){
 NikonZ8State s={0};s.active=true;
 s.config150d_latched[0x310/4]=3;s.config150d_latched[0x314/4]=1;
 s.config150d_latched[0x340/4]=1;s.config150d_latched[0x348/4]=records-1;
 s.config150d_latched[0x3a8/4]=1536;s.config150d_latched[0x33c/4]=bank;
 unsigned a=bank?0x370:0x350;
 uint64_t bus=BASE+UINT64_C(0x400000000);
 s.config150d_latched[a/4]=(uint32_t)bus;s.config150d_latched[(a+4)/4]=bus>>32;
 for(unsigned y=0;y<12;y++)for(unsigned x=0;x<30;x++)s.statistics_means[y][x]=1000+y*30+x;
 memset(ram,0xa5,sizeof(ram));valid_bytes=records*1536;
 irq_updates=retries=writes=0;return s;
}
'''
        check = r'''
int main(void){
 unsigned counts[]={20,40,64};
 for(unsigned k=0;k<3;k++)for(unsigned bank=0;bank<2;bank++){
  unsigned n=counts[k];NikonZ8State s=setup(n,bank);statistics_tick(&s);
  assert(s.statistics_frames==1 && s.statistics_bytes==n*720);
  assert(s.statistics_records==n && s.statistics_last_records==n);
  assert(s.statistics_events==1 && s.statistics_pending==0x20 && irq_updates==1);
  assert(!s.statistics_rejects && writes==n*12);
  for(unsigned i=0;i<sizeof(ram);i++){
   uint8_t expected=0xa5;
   if(i>=32 && i<32+n*1536){
    unsigned o=(i-32)%1536,y=o/64,x=(o%64)/2;
    if(y<12 && x<30){unsigned v=1000+y*30+x;expected=(o&1)?v>>8:v;}
   }
   assert(ram[i]==expected);
  }
  statistics_tick(&s);assert(s.statistics_frames==1 && irq_updates==1);
 }
 for(unsigned bad=0;bad<6;bad++){
  NikonZ8State s=setup(20,0);
  if(bad==0)s.config150d_latched[0x348/4]=20; // unsupported 21 records
  if(bad==1)s.config150d_latched[0x3a8/4]=768;
  if(bad==2)s.config150d_latched[0x310/4]=2;
  if(bad==3)s.config150d_latched[0x350/4]++;
  if(bad==4)valid_bytes--; // even a one-byte-short DMA span must fail
  if(bad==5)s.config150d_latched[0x354/4]=0;
  statistics_tick(&s);assert(s.statistics_rejects==1 && retries==1);
  assert(!writes && !irq_updates && !s.statistics_events && !s.statistics_pending);
  for(unsigned i=0;i<sizeof(ram);i++)assert(ram[i]==0xa5);
 }
 NikonZ8State s=setup(20,0);s.active=false;statistics_tick(&s);assert(!writes && !retries);
 puts("20/40/64 records, both banks, row padding, DMA guards and completion checks passed");
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            c=Path(tmp)/'statistics.c'; exe=Path(tmp)/'statistics'
            c.write_text(pre+tick+check)
            subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Wno-unused-parameter',str(c),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True)

if __name__ == '__main__':
    unittest.main()
