/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright (C) 2026 RdWing */
#include <stdint.h>
#include <stddef.h>
#include <assert.h>
typedef uint64_t hwaddr;
typedef struct { int engine1548_config_model; uint32_t engine1548_region[2][4][32]; } NikonZ8State;
static uint32_t *z8_region_word(NikonZ8State *s, hwaddr addr, unsigned size)
{
    if (!s->engine1548_config_model || size != 4 || (addr & 3) ||
        addr < 0x15480000 || addr >= 0x15488000) {
        return NULL;
    }
    unsigned offset = (addr - 0x15480000) % 0x4000;
    if (offset < 0x1800 || offset >= 0x1a00) {
        return NULL;
    }
    unsigned unit = (addr - 0x15480000) / 0x4000;
    unsigned bank = (offset - 0x1800) / 0x80;
    unsigned index = ((offset - 0x1800) % 0x80) / 4;
    return &s->engine1548_region[unit][bank][index];
}


int main(void) {
 NikonZ8State s={0};
 assert(!z8_region_word(&s,0x15485800,4));s.engine1548_config_model=1;
 for(unsigned u=0;u<2;u++) for(unsigned b=0;b<4;b++) for(unsigned i=0;i<32;i++) {
  hwaddr a=0x15481800+u*0x4000+b*0x80+i*4;
  uint32_t *p=z8_region_word(&s,a,4);assert(p==&s.engine1548_region[u][b][i]);*p=0x10000+u*128+b*32+i;
 }
 for(unsigned u=0;u<2;u++) for(unsigned b=0;b<4;b++) for(unsigned i=0;i<32;i++)
  assert(*z8_region_word(&s,0x15481800+u*0x4000+b*0x80+i*4,4)==0x10000+u*128+b*32+i);
 assert(!z8_region_word(&s,0x154817fc,4));assert(!z8_region_word(&s,0x15481a00,4));
 assert(!z8_region_word(&s,0x15485801,4));assert(!z8_region_word(&s,0x15485800,8));
 assert(!z8_region_word(&s,0x15489800,4));return 0;
}
