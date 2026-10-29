#!/usr/bin/env python3
# Copyright (C) 2026 RdWing: Z8 adaptation.
"""Exercise production playback admission, real pixel writes and IRQ ordering."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PlaybackResize(unittest.TestCase):
    def test_owned_nv16_bounds_pixels_padding_and_completion(self):
        directory = ROOT / 'qemu'
        capture = (directory / 'nikon-z8-capture-nv16.h').read_text()
        helpers = (capture[capture.index('static uint64_t capture_nv16_address'):capture.index('static bool capture_nv16_span')] +
                   capture[capture.index('static unsigned capture_nv16_coordinate'):capture.index('static bool capture_nv16_prepare')])
        source = (directory / 'nikon-z8-playback.h').read_text()
        source = source[:source.index('static char *z8_playback_state')]
        declarations = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <inttypes.h>
#include <assert.h>
#define MiB (1024*1024)
#define MEMTX_OK 0
#define MEMTXATTRS_UNSPECIFIED 0
#define g_malloc malloc
#define g_free free
#define BASE UINT64_C(0xa00000000)
typedef uint64_t hwaddr;
typedef struct {
 bool raw_pipeline_output_done,z8_e_armed,raw_histogram_luma,wave5_host_decoder_diagnostic;
 uint32_t raw_histogram[3][256];uint64_t raw_histogram_samples,raw_histogram_frames;unsigned raw_histogram_source;
 bool z8_jdec_on,z8_playback_requested,z8_playback_active,z8_playback_output_valid,z8_jdec_output_valid[2];
 uint8_t *z8_playback_pixels;
 uint64_t z8_jdec_y[2],z8_jdec_uv[2],z8_jdec_output_epoch[2],z8_playback_decode_epoch;
 unsigned z8_playback_decode_core;
 uint32_t z8_jdec_width[2],z8_jdec_height[2],z8_jdec_yp[2],z8_jdec_cp[2],z8_jdec_format[2];
 uint32_t engine1542_config[40][0x1000/4],engine1542_pending[40];
 uint32_t z8_playback_input[64],z8_playback_output[64],z8_playback_geometry[64];
 uint64_t z8_playback_requests,z8_playback_jobs,z8_playback_bytes;
 unsigned z8_playback_outputs_armed;
} NikonZ8State;
/* This isolated suite exercises JPEG/NV16 only. Actual decoder ownership
 * and NV12 DMA are covered by the actual-board controls. */
static bool wave5_decoder_surface_valid(NikonZ8State*s,unsigned token,uint64_t epoch){
 (void)s;(void)token;(void)epoch;return false;
}
static bool wave5_decoder_surface_find(NikonZ8State*s,uint64_t y,uint64_t uv,unsigned width,unsigned height,unsigned pitch,unsigned*token,uint64_t*epoch){
 (void)s;(void)y;(void)uv;(void)width;(void)height;(void)pitch;(void)token;(void)epoch;return false;
}
static uint8_t ram[4096];
static unsigned reads,writes,irq,invalid;
static unsigned expected_reads,expected_writes,fail_write;
static uint64_t read_address[32];static size_t read_bytes[32];
static NikonZ8State *writing_state;
static int address_space_memory;
static uint32_t engine1542_bases[40];
static bool dma_ram_range(NikonZ8State*s,uint64_t p,uint64_t n){
 (void)s;return p>=BASE&&n<=sizeof(ram)&&p-BASE<=sizeof(ram)-n;
}
static int address_space_read(void*a,uint64_t p,int attrs,void*b,size_t n){
 (void)a;(void)attrs;assert(dma_ram_range(NULL,p,n));
 read_address[reads]=p;read_bytes[reads]=n;reads++;memcpy(b,ram+p-BASE,n);return 0;
}
static int address_space_write(void*a,uint64_t p,int attrs,const void*b,size_t n){
 (void)a;(void)attrs;assert(dma_ram_range(NULL,p,n));assert(!writing_state->z8_playback_output_valid);
 writes++;if(fail_write==writes)return 1;memcpy(ram+p-BASE,b,n);return 0;
}
static void raw_pipeline_irq_update(NikonZ8State*s){
 assert(reads==expected_reads);
 if(s->engine1542_pending[1]==0x10011)assert(writes==expected_writes&&s->engine1542_pending[7]==0x1000&&s->z8_playback_output_valid);
 else assert(s->engine1542_pending[1]==0x10000);
 assert(!s->engine1542_pending[11]);irq++;
}
static void unknown_access(NikonZ8State*s,hwaddr a,uint64_t v,unsigned n,bool w){
 (void)s;(void)a;(void)v;(void)n;(void)w;invalid++;
}
'''
        checks = r'''
static void pair(uint32_t*c,unsigned off,uint64_t p){c[off/4]=(uint32_t)p;c[(off+4)/4]=p>>32;}
static void setup(NikonZ8State*s){
 memset(s,0,sizeof(*s));memset(ram,0xcd,sizeof(ram));
 writing_state=s;expected_reads=2;expected_writes=4;fail_write=0;
 reads=writes=irq=invalid=0;s->z8_jdec_on=true;s->z8_jdec_output_valid[0]=true;
 s->z8_jdec_output_epoch[0]=1;s->z8_jdec_format[0]=1;s->z8_jdec_y[0]=BASE;s->z8_jdec_uv[0]=BASE+256;
 s->z8_jdec_width[0]=8;s->z8_jdec_height[0]=4;s->z8_jdec_yp[0]=s->z8_jdec_cp[0]=12;
 uint32_t*a=s->engine1542_config[1],*b=s->engine1542_config[7],*f=s->engine1542_config[19];
 a[1]=0x5002;a[2]=0x50000000;a[3]=0x71000010;a[4]=1;a[0x40/4]=0x22;
 a[0x4c/4]=8;a[0x50/4]=4;a[0x38/4]=a[0x3c/4]=12;
 pair(a,0x20,BASE);pair(a,0x28,BASE+256);
 b[3]=0x41400010;b[4]=1;b[0x40/4]=0x22;b[0x38/4]=b[0x3c/4]=8;
 pair(b,0x20,BASE+512);pair(b,0x28,BASE+768);
 f[0]=2;f[1]=1;f[0x18/4]=8;f[0x1c/4]=4;f[0x2c/4]=4;f[0x30/4]=2;
 f[0x10/4]=f[0x14/4]=2<<14;s->engine1542_config[9][3]=0x41430010;
 s->engine1542_config[9][4]=1;s->engine1542_config[9][0x40/4]=0x22;
 s->engine1542_config[9][0x38/4]=s->engine1542_config[9][0x3c/4]=12;
 uint32_t*f6=s->engine1542_config[21];f6[0]=2;f6[1]=1;
 f6[0x10/4]=f6[0x14/4]=16384;f6[0x18/4]=f6[0x2c/4]=8;
 f6[0x1c/4]=f6[0x30/4]=4;
 for(unsigned r=0;r<4;r++)for(unsigned x=0;x<8;x++){
  ram[r*12+x]=r*10+x;ram[256+r*12+x]=100+r*10+x;
 }
}
static void produce_zoom(NikonZ8State*s){
 setup(s);s->engine1542_config[1][1]=0x1002;s->engine1542_config[1][2]=0x10000000;
 z8_playback_control(s,0x15421104,0x1001);
 assert(!invalid&&s->z8_playback_output_valid&&s->z8_playback_jobs==1);
 s->engine1542_pending[1]=s->engine1542_pending[7]=0;
}
static void select_crop(NikonZ8State*s){
 uint32_t*a=s->engine1542_config[1],*b=s->engine1542_config[7],*f=s->engine1542_config[19];
 a[1]=0x5002;a[2]=0x50000000;a[0x4c/4]=2;a[0x50/4]=1;
 a[0x38/4]=a[0x3c/4]=8;pair(a,0x20,BASE+522);pair(a,0x28,BASE+778);
 b[0x38/4]=b[0x3c/4]=4;pair(b,0x20,BASE+1024);pair(b,0x28,BASE+1280);
 memset(f,0,64*sizeof(*f));f[0]=2;f[1]=1;
 f[0x18/4]=f[0x2c/4]=2;f[0x1c/4]=f[0x30/4]=1;
 f[0x10/4]=f[0x14/4]=1<<14;
 expected_reads=4;expected_writes=6;
}
int main(void){
 NikonZ8State s;setup(&s);
 assert(z8_playback_control(&s,0x15421104,0x5001));
 assert(!s.z8_playback_requested&&s.z8_playback_requests==1&&reads==2&&writes==4&&irq==1);
 assert(s.z8_playback_jobs==1&&s.z8_playback_bytes==16&&!s.z8_playback_pixels);
 for(unsigned r=0;r<2;r++)for(unsigned x=0;x<8;x++){
  assert(ram[512+r*8+x]==(x<4?r*20+x*2:0xcd));
  assert(ram[768+r*8+x]==(x<4?100+r*20+(x&~1)*2+(x&1):0xcd));
 }
 z8_playback_control(&s,0x15421104,0x5001);assert(invalid==1&&writes==4);
 z8_playback_control(&s,0x15421104,0x1000);
 assert(invalid==2&&s.z8_playback_active&&s.engine1542_config[1][1]==0x5001&&irq==1);
 z8_playback_output_control(&s,9,0x15422604,1);assert(writes==4&&irq==1); /* Pulse is not DMA. */
 s.engine1542_pending[1]=s.engine1542_pending[7]=0;
 z8_playback_control(&s,0x15421104,0x5000);
 assert(s.engine1542_pending[1]==0x10000&&irq==2&&!s.z8_playback_active);
 s.engine1542_pending[1]=0;z8_playback_control(&s,0x15421104,0x5000);assert(irq==2);
 /* Z8 zoom keeps decoded ownership but changes both A1 selectors. The
  * nonzero phases and shift must affect real pixels, preserving padding. */
 setup(&s);s.engine1542_config[1][1]=0x1002;s.engine1542_config[1][2]=0x10000000;
 uint32_t*z=s.engine1542_config[19];z[0x8/4]=z[0xc/4]=4096;
 z[0x10/4]=z[0x14/4]=4096;z[0x20/4]=2;
 z8_playback_control(&s,0x15421104,0x1001);
 assert(!invalid&&reads==2&&writes==4&&irq==1&&s.z8_playback_jobs==1&&s.z8_playback_bytes==16);
 for(unsigned r=0;r<2;r++)for(unsigned x=0;x<8;x++){
  assert(ram[512+r*8+x]==(x<4?(r+1)*10+x+1:0xcd));
  assert(ram[768+r*8+x]==(x<4?100+(r+1)*10+x:0xcd));
 }
 z8_playback_control(&s,0x15421104,0x5000);
 assert(invalid==1&&s.z8_playback_active&&s.engine1542_config[1][1]==0x1001&&irq==1);
 s.engine1542_pending[1]=s.engine1542_pending[7]=0;
 z8_playback_control(&s,0x15421104,0x1000);
 assert(s.engine1542_pending[1]==0x10000&&!s.z8_playback_active&&irq==2);
 /* Crossed selectors, unobserved modes and opcode changes reject without
  * reading source RAM, writing pixels, publishing IRQs or changing state. */
 for(unsigned mode=0;mode<2;mode++){
  uint32_t selector=mode?0x1000:0x5000;
  setup(&s);s.engine1542_config[1][1]=selector|2;
  s.engine1542_config[1][2]=(mode?0x5000:0x1000)<<16;
  assert(!z8_playback_prepare(&s));
  z8_playback_control(&s,0x15421104,selector|1);
  assert(invalid==1&&!reads&&!writes&&!irq&&s.engine1542_config[1][1]==(selector|2));
  setup(&s);s.engine1542_config[1][1]=selector|2;s.engine1542_config[1][2]=selector<<16;
  z8_playback_control(&s,0x15421104,(mode?0x5000:0x1000)|1);
  assert(invalid==1&&!reads&&!writes&&!irq&&s.engine1542_config[1][1]==(selector|2));
  setup(&s);s.engine1542_config[1][1]=selector|2;s.engine1542_config[1][2]=selector<<16;
  s.z8_jdec_output_valid[0]=false;assert(!z8_playback_prepare(&s));
  setup(&s);s.engine1542_config[1][1]=selector|2;s.engine1542_config[1][2]=selector<<16;
  s.engine1542_config[19][0x10/4]=8<<14;assert(!z8_playback_prepare(&s));
  setup(&s);s.engine1542_config[1][1]=selector|2;s.engine1542_config[1][2]=selector<<16;
  pair(s.engine1542_config[7],0x20,BASE);assert(!z8_playback_prepare(&s));
  setup(&s);s.engine1542_config[1][1]=selector|2;s.engine1542_config[1][2]=selector<<16;
  assert(z8_playback_prepare(&s));s.z8_jdec_output_epoch[0]++;
  s.z8_playback_outputs_armed=2;z8_playback_run(&s);
  assert(invalid==1&&!writes&&!irq&&!s.z8_playback_pixels);
 }
 setup(&s);s.engine1542_config[1][1]=0x3002;s.engine1542_config[1][2]=0x30000000;
 assert(!z8_playback_prepare(&s));z8_playback_control(&s,0x15421104,0x3001);
 assert(invalid==1&&!reads&&!writes&&!irq);
 /* Only the just-produced 0x10 output supplies the observed 0x50 crop.
  * Input offsets need not be32-byte aligned; active-width reads alone
  * stay inside actual produced pixels, including the final source row. */
 produce_zoom(&s);select_crop(&s);z8_playback_control(&s,0x15421104,0x5001);
 assert(!invalid&&reads==4&&writes==6&&irq==2&&s.z8_playback_jobs==2&&s.z8_playback_output_valid);
 assert(read_address[2]==BASE+522&&read_address[3]==BASE+778&&read_bytes[2]==2&&read_bytes[3]==2);
 assert(ram[1024]==24&&ram[1025]==26&&ram[1026]==0xcd&&ram[1027]==0xcd);
 assert(ram[1280]==124&&ram[1281]==125&&ram[1282]==0xcd&&ram[1283]==0xcd);
 /* A second recursive crop is outside this explicitly qualified join. */
 s.engine1542_pending[1]=s.engine1542_pending[7]=0;
 pair(s.engine1542_config[1],0x20,BASE+1024);pair(s.engine1542_config[1],0x28,BASE+1280);
 pair(s.engine1542_config[7],0x20,BASE+1536);pair(s.engine1542_config[7],0x28,BASE+1792);
 s.engine1542_config[1][1]=0x5002;assert(!z8_playback_prepare(&s));
 for(unsigned failure=0;failure<10;failure++){
  produce_zoom(&s);select_crop(&s);
  uint32_t*a=s.engine1542_config[1];
  switch(failure){
   case 0:s.z8_playback_output_valid=false;break;
   case 1:s.z8_playback_requested=true;break;
   case 2:pair(a,0x28,BASE+780);break; /* unequal plane offsets */
   case 3:pair(a,0x20,BASE+523);pair(a,0x28,BASE+779);break; /* odd x */
   case 4:pair(a,0x20,BASE+524);pair(a,0x28,BASE+780);break; /* padding */
   case 5:a[0x4c/4]=4;break; /* extends past produced right edge */
   case 6:a[0x50/4]=2;break; /* extends past produced bottom edge */
   case 7:s.z8_jdec_output_epoch[0]++;break;
   case 8:s.z8_jdec_output_valid[0]=false;break;
   case 9:pair(s.engine1542_config[7],0x20,BASE+1032);break; /* destination remains aligned */
  }
  assert(!z8_playback_prepare(&s));assert(reads==2&&writes==4&&irq==1);
 }
 /* A partially failed producer cannot publish an owned output crop. */
 setup(&s);s.engine1542_config[1][1]=0x1002;s.engine1542_config[1][2]=0x10000000;fail_write=2;
 z8_playback_control(&s,0x15421104,0x1001);
 assert(invalid==1&&writes==2&&!irq&&!s.z8_playback_output_valid&&!s.z8_playback_jobs);
 select_crop(&s);assert(!z8_playback_prepare(&s));assert(reads==2&&writes==2&&!irq);
 setup(&s);s.z8_jdec_output_valid[0]=false;assert(!z8_playback_prepare(&s));
 setup(&s);s.z8_jdec_format[0]=2;assert(!z8_playback_prepare(&s));
 setup(&s);s.engine1542_pending[1]=0x10;assert(!z8_playback_prepare(&s));
 setup(&s);s.engine1542_pending[1]=0x10000;assert(!z8_playback_prepare(&s));
 setup(&s);s.engine1542_pending[7]=0x1000;assert(!z8_playback_prepare(&s));
 setup(&s);s.engine1542_pending[14]=0x10;assert(!z8_playback_prepare(&s));
 setup(&s);s.engine1542_config[19][0x10/4]=8<<14;assert(!z8_playback_prepare(&s));
 setup(&s);pair(s.engine1542_config[7],0x20,BASE);assert(!z8_playback_prepare(&s));
 setup(&s);pair(s.engine1542_config[7],0x20,BASE+4096);assert(!z8_playback_prepare(&s));
 assert(!z8_playback_span(&s,UINT64_MAX-31,64));assert(!reads&&!writes&&!irq);
 setup(&s);assert(z8_playback_prepare(&s));s.engine1542_config[9][8]=1;
 z8_playback_output_control(&s,9,0x15422604,1);assert(!invalid&&!writes&&!irq&&s.z8_playback_requested);
 z8_playback_output_control(&s,9,0x15422604,3);assert(invalid==1&&!writes&&!irq);g_free(s.z8_playback_pixels);
 setup(&s);assert(z8_playback_prepare(&s));s.z8_jdec_output_epoch[0]++;
 s.z8_playback_outputs_armed=2;z8_playback_run(&s);assert(invalid==1&&!writes&&!irq&&!s.z8_playback_pixels);
 /* A retained read cannot be replaced by later edits to source RAM. */
 setup(&s);assert(z8_playback_prepare(&s));memset(ram,0xee,48);s.z8_playback_outputs_armed=2;
 z8_playback_run(&s);assert(ram[512]==0&&ram[513]==2&&writes==4);
 setup(&s);assert(z8_playback_prepare(&s));z8_playback_control(&s,0x15421104,0x5000);
 assert(!writes&&irq==1&&!s.z8_playback_pixels&&!s.z8_playback_requested);z8_playback_run(&s);assert(!writes);
 setup(&s);s.raw_pipeline_output_done=s.z8_e_armed=true;
 uint32_t*e=s.engine1542_config[14];e[0]=1;e[1]=0xe0;e[2]=1;e[0x50/4]=0x11;
 assert(z8_playback_prepare(&s));z8_playback_histogram(&s);
 assert(s.engine1542_pending[14]==1&&s.raw_histogram_frames==1&&s.raw_histogram_samples==32&&s.raw_histogram_source==14);
 unsigned count=0;for(unsigned b=0;b<256;b++)count+=s.raw_histogram[0][b];assert(count==32&&s.raw_histogram[0][0xcd]==0);
 s.z8_e_armed=true;z8_playback_histogram(&s);assert(s.raw_histogram_frames==1);
 s.engine1542_pending[14]=0;e[1]=0xd0;z8_playback_histogram(&s);assert(!s.engine1542_pending[14]);
 e[1]=0xe0;e[2]=0;z8_playback_histogram(&s);assert(s.raw_histogram_frames==1);
 e[2]=1;e[0x50/4]=0;z8_playback_histogram(&s);assert(s.raw_histogram_frames==1);
 e[0x50/4]=0x11;s.raw_pipeline_output_done=false;z8_playback_histogram(&s);assert(s.raw_histogram_frames==1);
 z8_playback_control(&s,0x15421104,0x5000);
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp)
            (p / 'test.c').write_text(declarations + helpers + source + checks)
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', str(p / 'test.c'), '-o', str(p / 'test')], check=True)
            subprocess.run([str(p / 'test')], check=True, capture_output=True)


if __name__ == '__main__':
    unittest.main()
