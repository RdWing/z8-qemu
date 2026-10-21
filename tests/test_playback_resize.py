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
 bool raw_pipeline_output_done,z8_e_armed,raw_histogram_luma;
 uint32_t raw_histogram[3][256];uint64_t raw_histogram_samples,raw_histogram_frames;unsigned raw_histogram_source;
 bool z8_jdec_on,z8_playback_requested,z8_playback_active,z8_jdec_output_valid[2];
 uint8_t *z8_playback_pixels;
 uint64_t z8_jdec_y[2],z8_jdec_uv[2],z8_jdec_output_epoch[2],z8_playback_decode_epoch;
 unsigned z8_playback_decode_core;
 uint32_t z8_jdec_width[2],z8_jdec_height[2],z8_jdec_yp[2],z8_jdec_cp[2],z8_jdec_format[2];
 uint32_t engine1542_config[40][0x1000/4],engine1542_pending[40];
 uint32_t z8_playback_input[64],z8_playback_output[64],z8_playback_geometry[64];
 uint64_t z8_playback_requests,z8_playback_jobs,z8_playback_bytes;
 unsigned z8_playback_outputs_armed;
} NikonZ8State;
static uint8_t ram[4096];
static unsigned reads,writes,irq,invalid;
static int address_space_memory;
static uint32_t engine1542_bases[40];
static bool dma_ram_range(NikonZ8State*s,uint64_t p,uint64_t n){
 (void)s;return p>=BASE&&n<=sizeof(ram)&&p-BASE<=sizeof(ram)-n;
}
static int address_space_read(void*a,uint64_t p,int attrs,void*b,size_t n){
 (void)a;(void)attrs;assert(dma_ram_range(NULL,p,n));reads++;memcpy(b,ram+p-BASE,n);return 0;
}
static int address_space_write(void*a,uint64_t p,int attrs,const void*b,size_t n){
 (void)a;(void)attrs;assert(dma_ram_range(NULL,p,n));writes++;memcpy(ram+p-BASE,b,n);return 0;
}
static void raw_pipeline_irq_update(NikonZ8State*s){
 assert(reads==2);
 if(s->engine1542_pending[1]==0x10011)assert(writes==4&&s->engine1542_pending[7]==0x1000);
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
 z8_playback_output_control(&s,9,0x15422604,1);assert(writes==4&&irq==1); /* Pulse is not DMA. */
 s.engine1542_pending[1]=s.engine1542_pending[7]=0;
 z8_playback_control(&s,0x15421104,0x5000);
 assert(s.engine1542_pending[1]==0x10000&&irq==2&&!s.z8_playback_active);
 s.engine1542_pending[1]=0;z8_playback_control(&s,0x15421104,0x5000);assert(irq==2);
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
 z8_playback_output_control(&s,9,0x15422604,1);assert(invalid==1&&!writes);g_free(s.z8_playback_pixels);
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
