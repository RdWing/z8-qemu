/*
 * STM32F2XX Timer
 *
 * Copyright (c) 2014 Alistair Francis <alistair@alistair23.me>
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in
 * all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
 * THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 * THE SOFTWARE.
 */

#ifndef HW_STM32F2XX_TIMER_H
#define HW_STM32F2XX_TIMER_H

#include "hw/core/sysbus.h"
#include "qemu/timer.h"
#include "qom/object.h"

#define TIM_CR1      0x00
#define TIM_CR2      0x04
#define TIM_SMCR     0x08
#define TIM_DIER     0x0C
#define TIM_SR       0x10
#define TIM_EGR      0x14
#define TIM_CCMR1    0x18
#define TIM_CCMR2    0x1C
#define TIM_CCER     0x20
#define TIM_CNT      0x24
#define TIM_PSC      0x28
#define TIM_ARR      0x2C
#define TIM_CCR1     0x34
#define TIM_CCR2     0x38
#define TIM_CCR3     0x3C
#define TIM_CCR4     0x40
#define TIM_DCR      0x48
#define TIM_DMAR     0x4C
#define TIM_OR       0x50

#define TIM_CR1_CEN   1

#define TIM_EGR_UG 1

#define TIM_CCER_CC2E   (1 << 4)
#define TIM_CCMR1_OC2M2 (1 << 14)
#define TIM_CCMR1_OC2M1 (1 << 13)
#define TIM_CCMR1_OC2M0 (1 << 12)
#define TIM_CCMR1_OC2PE (1 << 11)

#define TIM_DIER_UIE  1
#define TIM_DIER_CC1IE (1 << 1)

#define TIM_SR_CC1IF (1 << 1)

#define TYPE_STM32F2XX_TIMER "stm32f2xx-timer"
typedef struct STM32F2XXTimerState STM32F2XXTimerState;
DECLARE_INSTANCE_CHECKER(STM32F2XXTimerState, STM32F2XXTIMER,
                         TYPE_STM32F2XX_TIMER)

struct STM32F2XXTimerState {
    /* <private> */
    SysBusDevice parent_obj;

    /* <public> */
    MemoryRegion iomem;
    QEMUTimer *timer;
    /* Output compare on channels 1-4: the next match of a channel whose
     * interrupt is enabled, and the time up to which matches have been
     * settled (see stm32f2xx_timer_cc_sync). The update event above is not
     * the only source on the part; the Z 6III body MCU's one-shot delays
     * are all compare matches. */
    QEMUTimer *cc_timer;
    int64_t cc_seen_ns;
    qemu_irq cc_irq;            /* sysbus IRQ 1; IRQ 0 when not connected */
    bool ccr_wraps;             /* "ccr-wraps": see stm32f2xx_timer_oc() */
    uint8_t ccr_wraps_named;    /* channels that have used it, for the log */
    bool cc_min_named;          /* held to STM32F2XX_CC_MIN_NS, logged */
    qemu_irq irq;

    int64_t tick_offset;
    uint64_t hit_time;
    uint64_t freq_hz;
    bool clock_stopped;
    int64_t clock_stop_ns, stopped_update_ns, stopped_compare_ns;

    uint32_t tim_cr1;
    uint32_t tim_cr2;
    uint32_t tim_smcr;
    uint32_t tim_dier;
    uint32_t tim_sr;
    uint32_t tim_egr;
    uint32_t tim_ccmr1;
    uint32_t tim_ccmr2;
    uint32_t tim_ccer;
    uint32_t tim_psc;
    uint32_t tim_arr;
    uint32_t tim_ccr1;
    uint32_t tim_ccr2;
    uint32_t tim_ccr3;
    uint32_t tim_ccr4;
    uint32_t tim_dcr;
    uint32_t tim_dmar;
    uint32_t tim_or;
};

/* An edge on timer input TIn (ti 0..3), for input capture. */
void stm32f2xx_timer_input(STM32F2XXTimerState *s, unsigned ti, bool level);

void stm32f2xx_timer_set_clock_stopped(STM32F2XXTimerState *s, bool stopped);

#endif /* HW_STM32F2XX_TIMER_H */
