# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Run the actual experimental scanout function against bounded mock RAM."""
from pathlib import Path
import subprocess,tempfile
p=Path(__file__).resolve().parent
s=(p.parent/'qemu/nikon-z8-lab.c').read_text()
body=s[s.index('static void engine1548_overlay_indexed('):s.index('static void engine1548_scanout_tick(')]
pre=r'''
#include <stdint.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>
#include <stdio.h>
#define MiB (1024*1024)
#define CLAMP(x,a,b) ((x)<(a)?(a):((x)>(b)?(b):(x)))
#define MEMTXATTRS_UNSPECIFIED 0
#define MEMTX_OK 0
static void clean(void *p){free(*(void**)p);}
#define g_autofree __attribute__((cleanup(clean)))
#define g_malloc malloc
#define g_free free
#define g_clear_pointer(p,f) do{f(*(p));*(p)=NULL;}while(0)
typedef struct {uint32_t pixels[4];} DisplaySurface;
static DisplaySurface surface;
static uint8_t ram[4096];
static int address_space_memory;
typedef struct {
 uint32_t engine1548_layer_fields[2][2][0x294/4];
 uint32_t engine1548_addresses[2][10][2];
 uint32_t engine1548_pair_parameters[2][2][4],engine1548_ratio_fields[2][2][6];
 uint32_t engine1548_coefficients[2][0x4000/4],engine1548_subunit_control[2][2];
 uint32_t engine1548_requested_bank[2],engine1548_active_bank[2];
 uint32_t engine1548_direct_fields[2][10],engine1548_direct_control[2];
 uint32_t engine1548_small_triplets[2][18],engine1548_layer_request[2][2];
 void *engine1548_console;
 bool raw_pipeline_model,engine1548_last_frame_has_video;
 uint64_t ram_size,engine1548_scanout_color,engine1548_scanout_alpha;
 unsigned engine1548_scanout_width,engine1548_scanout_height;
 uint64_t engine1548_scanout_frames,engine1548_video_frames,engine1548_video_y,engine1548_video_uv;
} NikonZ8State;
#define MACHINE(s) (s)
static bool dma_ram_range(NikonZ8State*s,uint64_t a,size_t n){return a>=0xa00000000ULL && n<=sizeof ram && a-0xa00000000ULL<=sizeof ram-n;}
static int address_space_read(void* unused,uint64_t a,int flags,void*out,size_t n){assert(a>=0xa00000000ULL&&a-0xa00000000ULL+n<=sizeof ram);memcpy(out,ram+(a-0xa00000000ULL),n);return 0;}
static void qemu_console_resize(void*c,unsigned w,unsigned h){assert(w==2&&h==2);}
static DisplaySurface*qemu_console_surface(void*c){return &surface;}
static uint8_t*surface_data(DisplaySurface*s){return (uint8_t*)s->pixels;}
static int surface_stride(DisplaySurface*s){return 8;}
static void qemu_console_update(void*c,int x,int y,unsigned w,unsigned h){}
'''
post=r'''
int main(void){
 NikonZ8State s={0};s.ram_size=sizeof ram;s.engine1548_console=&surface;
 uint32_t*l=s.engine1548_layer_fields[1][0];l[0]=2|(2<<16);l[0x240/4]=1;
 l[0x180/4]=4;l[0x1c0/4]=2;l[0x100/4]=0x800;l[0x104/4]=14;
 memset(ram+0x800,255,4);
 for(unsigned row=0;row<3;row++)s.engine1548_small_triplets[1][12+row]=64;
 for(unsigned bank=0;bank<4;bank++){
  unsigned off=0x100+bank*16;s.engine1548_addresses[1][2+bank][0]=off;s.engine1548_addresses[1][2+bank][1]=14;
  for(unsigned i=0;i<8;i+=4){ram[off+i]=ram[off+i+1]=40+bank*40;ram[off+i+2]=ram[off+i+3]=128;}
 }
 for(unsigned bank=0;bank<4;bank++){
  s.engine1548_requested_bank[1]=bank<<8;
  assert(engine1548_scanout_fetch(&s));assert(s.engine1548_active_bank[1]==bank);
  unsigned v=40+bank*40;assert(surface.pixels[0]==(0xff000000|v<<16|v<<8|v));
 }
 /* Indexed region clips at right/bottom and honors transparent palette0. */
 s.engine1548_subunit_control[1][1]=3;
 s.engine1548_pair_parameters[1][1][0]=0x05030027;
 s.engine1548_pair_parameters[1][1][3]=0x03020100;
 uint32_t *overlay=s.engine1548_layer_fields[1][1];
 overlay[6]=2|(2<<16);overlay[0x240/4]=1<<6;
 overlay[0x180/4+6]=2;overlay[0x200/4+6]=1|(1<<16);
 overlay[0x80/4+10]=0x900;overlay[0x80/4+11]=14;
 memset(ram+0x900,2,4);s.engine1548_coefficients[1][0x3000/4+2]=0xff00ff00;
 assert(engine1548_scanout_fetch(&s));assert(surface.pixels[3]==0xff00ff00);assert(surface.pixels[0]==0xffa0a0a0);
 s.engine1548_ratio_fields[1][1][5]=16;
 s.engine1548_coefficients[1][0x3400/4+2]=0x80000000;
 assert(engine1548_scanout_fetch(&s));assert(surface.pixels[3]==0xff505050);
 ram[0x900]=0;assert(engine1548_scanout_fetch(&s));assert(surface.pixels[3]==0xffa0a0a0);
 overlay[0x80/4+10]=0xfffffff0;assert(engine1548_scanout_fetch(&s));assert(surface.pixels[3]==0xffa0a0a0);
 overlay[0x80/4+10]=0x900;overlay[0x180/4+6]=1;
 assert(engine1548_scanout_fetch(&s));assert(surface.pixels[3]==0xffa0a0a0);
 puts("PASS indexed overlay: positioning, edge clipping, palette bank, partial alpha, transparency, invalid DMA and short stride");
 uint64_t frames=s.engine1548_scanout_frames;
 s.engine1548_requested_bank[1]=1<<8;s.engine1548_addresses[1][3][1]=0;
 assert(!engine1548_scanout_fetch(&s));assert(s.engine1548_active_bank[1]==3);assert(s.engine1548_scanout_frames==frames);
 assert(surface.pixels[0]==0xffa0a0a0);
 puts("PASS actual scanout: four distinct banks, pixel selection, active latch, rejected address preserves frame and active bank");
}
'''
with tempfile.TemporaryDirectory() as d:
 c=Path(d)/'test.c';exe=Path(d)/'test';c.write_text(pre+body+post)
 subprocess.run(['cc','-fsanitize=address,undefined','-fno-sanitize-recover=all','-g',str(c),'-o',str(exe)],check=True)
 subprocess.run([str(exe)],check=True)
