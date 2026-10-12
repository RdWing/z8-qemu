/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright (C) 2026 RdWing */
#include <stdint.h>
#include <stddef.h>
#include <assert.h>
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
typedef uint64_t hwaddr;
typedef struct { int bootstrap_fixtures; uint32_t serial5_config[5][8]; } NikonZ8State;
static uint32_t *serial5_config(NikonZ8State *s, hwaddr addr, unsigned size)
{
    /* Original 40c17510/5bc: mode +8/+c/+18 and divider +14.
     * Z8 40c17824 preserves the high half of +48 and sets its low16
     * configuration field, counterpart to +44. Retention only.
     * FIFO, transfer control and completion are deliberately not covered.
     */
    static const unsigned offsets[] = {8, 0xc, 0x14, 0x18, 0x10, 0x40, 0x44, 0x48};
    if (!s->bootstrap_fixtures || size != 4 || addr < 0x0e200100 || addr >= 0x0e200600) {
        return NULL;
    }
    for (unsigned i = 0; i < ARRAY_SIZE(offsets); i++) {
        if ((addr & 255) == offsets[i]) {
            return &s->serial5_config[(addr - 0x0e200100) / 0x100][i];
        }
    }
    return NULL;
}


int main(void) {NikonZ8State s={0};assert(!serial5_config(&s,0xe200148,4));s.bootstrap_fixtures=1;
for(unsigned c=0;c<5;c++){uint32_t *p=serial5_config(&s,0xe200148+256*c,4);assert(p==&s.serial5_config[c][7]);*p=0xabcd1234+c;}
for(unsigned c=0;c<5;c++)assert(*serial5_config(&s,0xe200148+256*c,4)==0xabcd1234+c);
assert(!serial5_config(&s,0xe200648,4));assert(!serial5_config(&s,0xe200148,8));assert(!serial5_config(&s,0xe200149,4));return 0;}
