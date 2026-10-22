# SPDX-License-Identifier: GPL-2.0-or-later
"""Candidate sync wires pass GPIO levels and preserve original IRQ ownership."""
from pathlib import Path
import unittest
from source_helpers import function
from test_shared221 import check

class NativeWires(unittest.TestCase):
    def test_request_has_no_fabricated_reply_and_original_edge_owns_irq(self):
        source=(Path(__file__).resolve().parents[1]/'qemu/nikon-z8-mcu.h').read_text()
        production='\n'.join(function(source,n) for n in
            ('z8_mcu_gpio_update','z8_mcu_gpio_read','z8_mcu_gpio_write','z8_mcu_pin_out'))
        check(r'''
#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <assert.h>
typedef uint64_t hwaddr;
typedef struct { uint32_t moder,odr,level; } GPIO;
typedef struct NikonZ8State NikonZ8State;
typedef struct { NikonZ8State *owner;struct { GPIO gpio[11]; } chip;unsigned supply_port,supply_pin;int panel;int irq[3]; } Z8McuBridge;
static void z8_mcu_main_supply(Z8McuBridge *m,bool level) { (void)m;(void)level;assert(0); }
struct NikonZ8State { Z8McuBridge *native_mcu;bool mcu_capture_sync_wires;uint32_t syscon[0x2000],gpio_irq_config[2][8]; };
static int levels[3],drives;
static void qemu_set_irq(int n,int v){levels[n]=v;}
static void z8_stm32_gpio_drive(GPIO*g,unsigned bit,bool level){g->level=(g->level&~(1u<<bit))|((uint32_t)level<<bit);drives++;}
static void z8_toplcd_scs(int*p,bool v){(void)p;(void)v;}
static void z8_toplcd_disp(int*p,bool v){(void)p;(void)v;}
static void z8_toplcd_start(int*p,bool v){(void)p;(void)v;}
#define QEMU_CLOCK_VIRTUAL 0
static int64_t qemu_clock_get_ns(int n){(void)n;return 0;}
typedef struct { struct { uint64_t pc; } env; } CPU;
static CPU *current_cpu;
#define ARM_CPU(x) (x)
''' + production + r'''
int main(void){
 NikonZ8State s={0};Z8McuBridge m={.owner=&s,.irq={0,1,2}};s.native_mcu=&m;
 uint32_t initial=0x204;s.syscon[0x100c/4]=initial;
 uint32_t value=z8_mcu_gpio_write(&s,0xd15100c,0x10001000);
 assert(value==(initial|0x1000)&&drives==0&&!(s.syscon[0x100c/4]&0x80));
 s.mcu_capture_sync_wires=true;
 value=z8_mcu_gpio_write(&s,0xd15100c,0x10001000);s.syscon[0x100c/4]=value;
 assert(drives==1&&(m.chip.gpio[5].level&0x10)&&!(value&0x80));
 assert(!s.gpio_irq_config[0][2]&&!levels[2]); /* request alone is no completion */
 m.chip.gpio[3].moder=1u<<14;m.chip.gpio[3].odr=0x80;
 assert(z8_mcu_gpio_read(&s,0xd15100c,initial)==(initial|0x80));
 s.gpio_irq_config[0][5]=0x80;s.gpio_irq_config[0][6]=0x80;
 z8_mcu_pin_out(&m,3,7,true);
 assert((s.syscon[0x100c/4]&0x80)&&(s.gpio_irq_config[0][2]&0x80)&&levels[2]);
 assert((s.syscon[0x100c/4]&~0x80u)==(initial|0x1000));
 s.gpio_irq_config[0][0]=0x80;z8_mcu_gpio_update(&s);assert(!levels[2]&&(s.gpio_irq_config[0][2]&0x80));
 s.gpio_irq_config[0][0]=0;z8_mcu_gpio_update(&s);assert(levels[2]);
 s.gpio_irq_config[0][2]=0;z8_mcu_gpio_update(&s);assert(!levels[2]);
 s.gpio_irq_config[0][5]=0;m.chip.gpio[3].odr=0;z8_mcu_pin_out(&m,3,7,false);
 assert(!(s.syscon[0x100c/4]&0x80)&&(s.gpio_irq_config[0][2]&0x80)&&levels[2]);
 value=z8_mcu_gpio_write(&s,0xd15100c,0x10000000);s.syscon[0x100c/4]=value;
 assert(drives==2&&!(m.chip.gpio[5].level&0x10)&&!(value&0x80));
 s.mcu_capture_sync_wires=false;s.gpio_irq_config[0][2]=0;z8_mcu_gpio_update(&s);
 z8_mcu_pin_out(&m,3,7,true);assert(!(s.syscon[0x100c/4]&0x80)&&!s.gpio_irq_config[0][2]&&!levels[2]);
 return 0;
}
''')
