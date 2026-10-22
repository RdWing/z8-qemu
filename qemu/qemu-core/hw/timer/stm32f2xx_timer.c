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

#include "qemu/osdep.h"
#include "hw/core/irq.h"
#include "hw/core/qdev-properties.h"
#include "hw/timer/stm32f2xx_timer.h"
#include "migration/vmstate.h"
#include "qemu/log.h"
#include "qemu/error-report.h"
#include "qemu/module.h"

#ifndef STM_TIMER_ERR_DEBUG
#define STM_TIMER_ERR_DEBUG 0
#endif

#define DB_PRINT_L(lvl, fmt, args...) do { \
    if (STM_TIMER_ERR_DEBUG >= lvl) { \
        qemu_log("%s: " fmt, __func__, ## args); \
    } \
} while (0)

#define DB_PRINT(fmt, args...) DB_PRINT_L(1, fmt, ## args)

static void stm32f2xx_timer_set_alarm(STM32F2XXTimerState *s, int64_t now);

/*
 * Output compare, channels 1-4 (RM0386 18.3.8 and 18.4.5): whenever the
 * counter reaches CCRx on a channel in output mode (CCMRx.CCxS = 00), CCxIF
 * is set, and with DIER.CCxIE that pends the timer's interrupt. The counter
 * runs from 0 to ARR and wraps, so a channel matches once every ARR + 1
 * ticks, the first time (CCRx - CNT) mod (ARR + 1) ticks from now.
 *
 * The firmware on the Z 6III's body MCU uses this as its one-shot delay:
 * it writes CCRx = CNT + n and sets CCxIE -- TIM3 channel 3 is the shutter
 * service's 30-tick settle delay before it reads the shutter's position
 * sensors -- so the match has to come n ticks after the write. (The
 * channel-1-only version this replaces fired every CCR1 * (PSC + 1) ticks
 * from the write, which for CCRx = CNT + n is a delay of CNT + n.)
 *
 * One declared deviation, off unless the board sets "ccr-wraps": with it, a
 * CCRx beyond ARR matches at CCRx mod (ARR + 1) instead of never. The
 * Z 6III body MCU's switch service arms TIM10 (ARR = 499) at CCR1 = CNT +
 * 500 for the first snapshot of its switches, and nothing else takes that
 * snapshot or sends the EXPEED a key report; RM0386 says such a match
 * never happens, yet the camera evidently gets its key report. Until that
 * is explained, the board asks for the reading that makes the firmware's
 * "one period later" mean what it plainly intends. Each channel that uses
 * it is named once on stderr.
 *
 * The match interrupt goes out on sysbus IRQ 1 when that is connected --
 * TIM1 and TIM8 have a capture/compare vector of their own on the part
 * (TIM1_CC, TIM8_CC) -- and on IRQ 0 with the update event otherwise, which
 * is the one vector the general-purpose timers have.
 *
 * Matches are settled lazily: cc_seen_ns is the time up to which they have
 * been accounted, and stm32f2xx_timer_cc_sync() settles (cc_seen_ns, now]
 * before SR is read and before any register is written, with the settings
 * that were in force. Only channels whose interrupt is enabled get a host
 * timer (cc_timer, at the next match); a flag that is only polled is set
 * when SR is read, so free-running PWM channels cost nothing per period.
 *
 * A second declared deviation: the host timer is never set closer than
 * STM32F2XX_CC_MIN_NS ahead. The virtual clock follows the host's, so a
 * compare interrupt every few tens of nanoseconds re-arms itself in the past
 * on every callback and the main loop never leaves its timer list -- the
 * whole machine, QMP and gdbstub included, stops answering. That happened
 * the first time the Z 6III's body MCU was told to start a movie recording.
 * Matches inside the interval are still all settled, as one CCxIF and one
 * interrupt, which is what the part does when its handler is slower than
 * the period. The first time a timer needs it, its settings go to stderr.
 */
#define STM32F2XX_CC_MIN_NS 10000
static uint32_t stm32f2xx_timer_ccr(STM32F2XXTimerState *s, unsigned ch)
{
    switch (ch) {
    case 0:
        return s->tim_ccr1;
    case 1:
        return s->tim_ccr2;
    case 2:
        return s->tim_ccr3;
    default:
        return s->tim_ccr4;
    }
}

/* A channel that can match: output mode, and a CCRx the counter reaches. */
static bool stm32f2xx_timer_oc(STM32F2XXTimerState *s, unsigned ch)
{
    uint32_t ccmr = ch < 2 ? s->tim_ccmr1 : s->tim_ccmr2;

    if ((ccmr >> (8 * (ch & 1))) & 3) {
        return false;                           /* an input channel */
    }
    if (stm32f2xx_timer_ccr(s, ch) <= s->tim_arr) {
        return true;
    }
    if (!s->ccr_wraps) {
        return false;                           /* RM0386: never reached */
    }
    if (!(s->ccr_wraps_named & (1u << ch))) {
        s->ccr_wraps_named |= 1u << ch;
        g_autofree char *path = object_get_canonical_path(OBJECT(s));

        warn_report("%s: CCR%u = %u is beyond ARR = %u; matching it at "
                    "CCR mod (ARR + 1), the declared deviation \"ccr-wraps\" "
                    "asks for", path, ch + 1, stm32f2xx_timer_ccr(s, ch),
                    s->tim_arr);
    }
    return true;
}

static inline int64_t stm32f2xx_ns_to_ticks(STM32F2XXTimerState *s, int64_t t);

/* The earliest virtual time at which stm32f2xx_ns_to_ticks() reaches the
 * absolute tick count `ticks`. */
static int64_t stm32f2xx_ticks_to_ns(STM32F2XXTimerState *s, uint64_t ticks)
{
    return muldiv64(ticks * (s->tim_psc + 1), 1000000000ULL, s->freq_hz) + 1;
}

/* Ticks from absolute tick `t` to channel ch's next match (1..ARR + 1). */
static uint64_t stm32f2xx_timer_cc_due(STM32F2XXTimerState *s, unsigned ch,
                                       int64_t t)
{
    int64_t period = (int64_t)s->tim_arr + 1;
    int64_t pos = (t - s->tick_offset) % period;
    int64_t d;

    if (pos < 0) {
        pos += period;
    }
    d = ((int64_t)(stm32f2xx_timer_ccr(s, ch) % period) - pos + period) %
        period;
    return d ? d : period;
}

static void stm32f2xx_timer_cc_sync(STM32F2XXTimerState *s, int64_t now)
{
    int64_t from = stm32f2xx_ns_to_ticks(s, s->cc_seen_ns);
    int64_t to = stm32f2xx_ns_to_ticks(s, now);
    bool irq = false;

    s->cc_seen_ns = now;
    if (to <= from || !(s->tim_cr1 & TIM_CR1_CEN) || !s->tim_arr) {
        return;
    }
    for (unsigned ch = 0; ch < 4; ch++) {
        if (stm32f2xx_timer_oc(s, ch) &&
            stm32f2xx_timer_cc_due(s, ch, from) <= (uint64_t)(to - from)) {
            s->tim_sr |= 2u << ch;                      /* CCxIF */
            irq |= s->tim_dier & (2u << ch);            /* CCxIE */
        }
    }
    if (irq) {
        qemu_irq_pulse(s->cc_irq ? s->cc_irq : s->irq);
    }
}

static void stm32f2xx_timer_set_cc_alarm(STM32F2XXTimerState *s)
{
    int64_t now_t;
    uint64_t best = 0;

    timer_del(s->cc_timer);
    if (!(s->tim_cr1 & TIM_CR1_CEN) || !s->tim_arr) {
        return;
    }
    now_t = stm32f2xx_ns_to_ticks(s, s->cc_seen_ns);
    for (unsigned ch = 0; ch < 4; ch++) {
        if (s->tim_dier & (2u << ch) && stm32f2xx_timer_oc(s, ch)) {
            uint64_t d = stm32f2xx_timer_cc_due(s, ch, now_t);

            best = best && best < d ? best : d;
        }
    }
    if (best) {
        int64_t at = stm32f2xx_ticks_to_ns(s, now_t + best);

        if (at - s->cc_seen_ns < STM32F2XX_CC_MIN_NS) {
            if (!s->cc_min_named) {
                g_autofree char *path = object_get_canonical_path(OBJECT(s));

                s->cc_min_named = true;
                warn_report("%s: compare match due in %" PRId64 " ns "
                            "(ARR %u PSC %u CCR %u/%u/%u/%u DIER 0x%x CCMR "
                            "0x%x/0x%x, %" PRIu64 " Hz); interrupts held to "
                            "one per %d ns from here on",
                            path, at - s->cc_seen_ns, s->tim_arr, s->tim_psc,
                            s->tim_ccr1, s->tim_ccr2, s->tim_ccr3, s->tim_ccr4,
                            s->tim_dier, s->tim_ccmr1, s->tim_ccmr2,
                            s->freq_hz, STM32F2XX_CC_MIN_NS);
            }
            at = s->cc_seen_ns + STM32F2XX_CC_MIN_NS;
        }
        timer_mod(s->cc_timer, at);
    }
}

static void stm32f2xx_timer_cc_interrupt(void *opaque)
{
    STM32F2XXTimerState *s = opaque;

    stm32f2xx_timer_cc_sync(s, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL));
    stm32f2xx_timer_set_cc_alarm(s);
}

static void stm32f2xx_timer_interrupt(void *opaque)
{
    STM32F2XXTimerState *s = opaque;

    DB_PRINT("Interrupt\n");

    if ((s->tim_cr1 & TIM_CR1_CEN) && s->tim_arr) {
        s->tim_sr |= 1;
        if (s->tim_dier & TIM_DIER_UIE) {
            qemu_irq_pulse(s->irq);
        }
        stm32f2xx_timer_set_alarm(s, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL));
    }

    if (s->tim_ccmr1 & (TIM_CCMR1_OC2M2 | TIM_CCMR1_OC2M1) &&
        !(s->tim_ccmr1 & TIM_CCMR1_OC2M0) &&
        s->tim_ccmr1 & TIM_CCMR1_OC2PE &&
        s->tim_ccer & TIM_CCER_CC2E) {
        /* PWM 2 - Mode 1 */
        DB_PRINT("PWM2 Duty Cycle: %d%%\n",
                s->tim_ccr2 / (100 * (s->tim_psc + 1)));
    }
}

static inline int64_t stm32f2xx_ns_to_ticks(STM32F2XXTimerState *s, int64_t t)
{
    return muldiv64(t, s->freq_hz, 1000000000ULL) / (s->tim_psc + 1);
}

static void stm32f2xx_timer_set_alarm(STM32F2XXTimerState *s, int64_t now)
{
    uint64_t ticks;
    int64_t now_ticks;
    int64_t position, period = (int64_t)s->tim_arr + 1;

    timer_del(s->timer);
    if (s->tim_arr == 0 || !(s->tim_cr1 & TIM_CR1_CEN)) {
        return;
    }

    DB_PRINT("Alarm set at: 0x%x\n", s->tim_cr1);

    now_ticks = stm32f2xx_ns_to_ticks(s, now);
    position = (now_ticks - s->tick_offset) % period;
    if (position < 0) {
        position += period;
    }
    ticks = period - position;

    DB_PRINT("Alarm set in %d ticks\n", (int) ticks);

    /* An absolute virtual deadline, like cc_timer. Do not add now twice.
     * Count 0..ARR inclusive and round to the first ns reaching overflow.
     */
    s->hit_time = stm32f2xx_ticks_to_ns(s, now_ticks + ticks);

    timer_mod(s->timer, s->hit_time);
    DB_PRINT("Wait Time: %" PRId64 " ticks\n", s->hit_time);
}

static void stm32f2xx_timer_reset(DeviceState *dev)
{
    STM32F2XXTimerState *s = STM32F2XXTIMER(dev);
    int64_t now = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);

    timer_del(s->timer);
    timer_del(s->cc_timer);
    s->hit_time = 0;
    s->cc_seen_ns = now;
    s->tim_cr1 = 0;
    s->tim_cr2 = 0;
    s->tim_smcr = 0;
    s->tim_dier = 0;
    s->tim_sr = 0;
    s->tim_egr = 0;
    s->tim_ccmr1 = 0;
    s->tim_ccmr2 = 0;
    s->tim_ccer = 0;
    s->tim_psc = 0;
    s->tim_arr = 0;
    s->tim_ccr1 = 0;
    s->tim_ccr2 = 0;
    s->tim_ccr3 = 0;
    s->tim_ccr4 = 0;
    s->tim_dcr = 0;
    s->tim_dmar = 0;
    s->tim_or = 0;

    s->tick_offset = stm32f2xx_ns_to_ticks(s, now);
}

/* The counter runs 0..ARR and wraps (RM0386 18.3.2), so that is what it
 * reads: the firmware's delays are CCRx = CNT + n, and an unwrapped count
 * put them anywhere in the 16-bit range. */
static uint32_t stm32f2xx_timer_cnt(STM32F2XXTimerState *s)
{
    int64_t c = stm32f2xx_ns_to_ticks(s,
                    qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL)) - s->tick_offset;
    int64_t period = (int64_t)s->tim_arr + 1;

    if (!s->tim_arr) {
        return c;
    }
    c %= period;
    return c < 0 ? c + period : c;
}

/*
 * Input capture (RM0386 18.3.5): the board reports a level change on
 * timer input TIn (ti = 0..3 for TI1..TI4). A channel in input mode whose
 * CCxS selects that input (01: its own, 10: its pair's; 11, TRC, is not
 * modelled), whose CCxE is set and whose CCxP/CCxNP edge it is (00
 * rising, 01 falling, 11 both) latches CNT into CCRx and sets CCxIF --
 * CCxOF as well if CCxIF was still set -- and interrupts if CCxIE is set.
 * The input filter and prescaler (ICxF, ICxPSC) are not modelled: every
 * edge the board reports is one clean capture. The Z 6III body MCU reads
 * its shutter's position sensors this way.
 */
void stm32f2xx_timer_input(STM32F2XXTimerState *s, unsigned ti, bool level)
{
    bool irq = false;

    for (unsigned ch = 0; ch < 4; ch++) {
        uint32_t ccmr = ch < 2 ? s->tim_ccmr1 : s->tim_ccmr2;
        unsigned ccs = (ccmr >> (8 * (ch & 1))) & 3;
        unsigned ccer = s->tim_ccer >> (4 * ch);
        bool p = ccer & 2, np = ccer & 8;

        if (ccs == 0 || ccs == 3 || (ccs == 1 ? ch : ch ^ 1) != ti ||
            !(ccer & 1)) {
            continue;
        }
        if (!(p && np) && level == p) {
            continue;                       /* not the edge it waits for */
        }
        switch (ch) {
        case 0:
            s->tim_ccr1 = stm32f2xx_timer_cnt(s);
            break;
        case 1:
            s->tim_ccr2 = stm32f2xx_timer_cnt(s);
            break;
        case 2:
            s->tim_ccr3 = stm32f2xx_timer_cnt(s);
            break;
        default:
            s->tim_ccr4 = stm32f2xx_timer_cnt(s);
            break;
        }
        if (s->tim_sr & (2u << ch)) {
            s->tim_sr |= 0x200u << ch;          /* CCxOF */
        }
        s->tim_sr |= 2u << ch;                  /* CCxIF */
        irq |= s->tim_dier & (2u << ch);        /* CCxIE */
    }
    if (irq) {
        qemu_irq_pulse(s->cc_irq ? s->cc_irq : s->irq);
    }
}

static uint64_t stm32f2xx_timer_read(void *opaque, hwaddr offset,
                           unsigned size)
{
    STM32F2XXTimerState *s = opaque;

    DB_PRINT("Read 0x%"HWADDR_PRIx"\n", offset);

    switch (offset) {
    case TIM_CR1:
        return s->tim_cr1;
    case TIM_CR2:
        return s->tim_cr2;
    case TIM_SMCR:
        return s->tim_smcr;
    case TIM_DIER:
        return s->tim_dier;
    case TIM_SR:
        stm32f2xx_timer_cc_sync(s, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL));
        return s->tim_sr;
    case TIM_EGR:
        return s->tim_egr;
    case TIM_CCMR1:
        return s->tim_ccmr1;
    case TIM_CCMR2:
        return s->tim_ccmr2;
    case TIM_CCER:
        return s->tim_ccer;
    case TIM_CNT:
        return stm32f2xx_timer_cnt(s);
    case TIM_PSC:
        return s->tim_psc;
    case TIM_ARR:
        return s->tim_arr;
    case TIM_CCR1:
        return s->tim_ccr1;
    case TIM_CCR2:
        return s->tim_ccr2;
    case TIM_CCR3:
        return s->tim_ccr3;
    case TIM_CCR4:
        return s->tim_ccr4;
    case TIM_DCR:
        return s->tim_dcr;
    case TIM_DMAR:
        return s->tim_dmar;
    case TIM_OR:
        return s->tim_or;
    default:
        qemu_log_mask(LOG_GUEST_ERROR,
                      "%s: Bad offset 0x%"HWADDR_PRIx"\n", __func__, offset);
    }

    return 0;
}

static void stm32f2xx_timer_write_reg(STM32F2XXTimerState *s, hwaddr offset,
                                      uint64_t val64, unsigned size)
{
    uint32_t value = val64;
    int64_t now = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    uint32_t timer_val = 0;

    DB_PRINT("Write 0x%x, 0x%"HWADDR_PRIx"\n", value, offset);

    switch (offset) {
    case TIM_CR1:
        s->tim_cr1 = value;
        stm32f2xx_timer_set_alarm(s, now);
        return;
    case TIM_CR2:
        s->tim_cr2 = value;
        return;
    case TIM_SMCR:
        s->tim_smcr = value;
        return;
    case TIM_DIER: {
        /* The request is a level, SR & DIER (RM0386 18.4.4, 18.4.5):
         * enabling a source whose flag is already set requests at once.
         * This model raises requests as pulses at the event, so a flag set
         * while its enable was clear gets its pulse here. The Z 6III body
         * MCU sets CC3IF by software (EGR CC3G, sub_804D908) and only then
         * enables CC3IE (sub_804DC68); without this its shutter-sensor
         * debounce never ended. */
        uint32_t newly;

        stm32f2xx_timer_cc_sync(s, now);
        newly = value & ~s->tim_dier & s->tim_sr;
        s->tim_dier = value;
        if (newly & 1) {
            qemu_irq_pulse(s->irq);
        }
        if (newly & 0x1e) {
            qemu_irq_pulse(s->cc_irq ? s->cc_irq : s->irq);
        }
        return;
    }
    case TIM_SR:
        /* This is set by hardware and cleared by software */
        s->tim_sr &= value;
        return;
    case TIM_EGR:
        s->tim_egr = value;
        if (value & 0x1e) {
            /* CC1G..CC4G (RM0386 18.4.6): a capture/compare event by
             * software -- CCxIF, CCxOF if it was still set, an input
             * channel's CCRx takes CNT, and CCxIE interrupts. Firmware
             * that finds a compare deadline already past fires it this
             * way (the Z 6III body MCU's sub_803A438 -> sub_804D908, its
             * shutter-sensor debounce); ignored, that event never came. */
            bool irq = false;

            for (unsigned ch = 0; ch < 4; ch++) {
                uint32_t ccmr = ch < 2 ? s->tim_ccmr1 : s->tim_ccmr2;

                if (!(value & (2u << ch))) {
                    continue;
                }
                if ((ccmr >> (8 * (ch & 1))) & 3) {
                    uint32_t cnt = stm32f2xx_timer_cnt(s);

                    switch (ch) {
                    case 0:
                        s->tim_ccr1 = cnt;
                        break;
                    case 1:
                        s->tim_ccr2 = cnt;
                        break;
                    case 2:
                        s->tim_ccr3 = cnt;
                        break;
                    default:
                        s->tim_ccr4 = cnt;
                        break;
                    }
                }
                if (s->tim_sr & (2u << ch)) {
                    s->tim_sr |= 0x200u << ch;          /* CCxOF */
                }
                s->tim_sr |= 2u << ch;                  /* CCxIF */
                irq |= s->tim_dier & (2u << ch);        /* CCxIE */
            }
            if (irq) {
                qemu_irq_pulse(s->cc_irq ? s->cc_irq : s->irq);
            }
        }
        if (s->tim_egr & TIM_EGR_UG) {
            timer_val = 0;
            break;
        }
        return;
    case TIM_CCMR1:
        s->tim_ccmr1 = value;
        return;
    case TIM_CCMR2:
        s->tim_ccmr2 = value;
        return;
    case TIM_CCER:
        s->tim_ccer = value;
        return;
    case TIM_PSC:
        timer_val = stm32f2xx_ns_to_ticks(s, now) - s->tick_offset;
        s->tim_psc = value & 0xFFFF;
        break;
    case TIM_CNT:
        timer_val = value;
        break;
    case TIM_ARR:
        s->tim_arr = value;
        stm32f2xx_timer_set_alarm(s, now);
        return;
    case TIM_CCR1:
        s->tim_ccr1 = value;
        return;
    case TIM_CCR2:
        s->tim_ccr2 = value;
        return;
    case TIM_CCR3:
        s->tim_ccr3 = value;
        return;
    case TIM_CCR4:
        s->tim_ccr4 = value;
        return;
    case TIM_DCR:
        s->tim_dcr = value;
        return;
    case TIM_DMAR:
        s->tim_dmar = value;
        return;
    case TIM_OR:
        s->tim_or = value;
        return;
    default:
        qemu_log_mask(LOG_GUEST_ERROR,
                      "%s: Bad offset 0x%"HWADDR_PRIx"\n", __func__, offset);
        return;
    }

    /* This means that a register write has affected the timer in a way that
     * requires a refresh of both tick_offset and the alarm.
     */
    s->tick_offset = stm32f2xx_ns_to_ticks(s, now) - timer_val;
    stm32f2xx_timer_set_alarm(s, now);
}

/* Every register write: settle the compare matches the old settings made,
 * then let the new ones decide the next. */
static void stm32f2xx_timer_write(void *opaque, hwaddr offset,
                        uint64_t val64, unsigned size)
{
    STM32F2XXTimerState *s = opaque;

    stm32f2xx_timer_cc_sync(s, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL));
    stm32f2xx_timer_write_reg(s, offset, val64, size);
    stm32f2xx_timer_set_cc_alarm(s);
}

static const MemoryRegionOps stm32f2xx_timer_ops = {
    .read = stm32f2xx_timer_read,
    .write = stm32f2xx_timer_write,
    .endianness = DEVICE_NATIVE_ENDIAN,
};

static const VMStateDescription vmstate_stm32f2xx_timer = {
    .name = TYPE_STM32F2XX_TIMER,
    .version_id = 1,
    .minimum_version_id = 1,
    .fields = (const VMStateField[]) {
        VMSTATE_INT64(tick_offset, STM32F2XXTimerState),
        VMSTATE_UINT32(tim_cr1, STM32F2XXTimerState),
        VMSTATE_UINT32(tim_cr2, STM32F2XXTimerState),
        VMSTATE_UINT32(tim_smcr, STM32F2XXTimerState),
        VMSTATE_UINT32(tim_dier, STM32F2XXTimerState),
        VMSTATE_UINT32(tim_sr, STM32F2XXTimerState),
        VMSTATE_UINT32(tim_egr, STM32F2XXTimerState),
        VMSTATE_UINT32(tim_ccmr1, STM32F2XXTimerState),
        VMSTATE_UINT32(tim_ccmr2, STM32F2XXTimerState),
        VMSTATE_UINT32(tim_ccer, STM32F2XXTimerState),
        VMSTATE_UINT32(tim_psc, STM32F2XXTimerState),
        VMSTATE_UINT32(tim_arr, STM32F2XXTimerState),
        VMSTATE_UINT32(tim_ccr1, STM32F2XXTimerState),
        VMSTATE_UINT32(tim_ccr2, STM32F2XXTimerState),
        VMSTATE_UINT32(tim_ccr3, STM32F2XXTimerState),
        VMSTATE_UINT32(tim_ccr4, STM32F2XXTimerState),
        VMSTATE_UINT32(tim_dcr, STM32F2XXTimerState),
        VMSTATE_UINT32(tim_dmar, STM32F2XXTimerState),
        VMSTATE_UINT32(tim_or, STM32F2XXTimerState),
        VMSTATE_END_OF_LIST()
    }
};

static const Property stm32f2xx_timer_properties[] = {
    DEFINE_PROP_BOOL("ccr-wraps", struct STM32F2XXTimerState, ccr_wraps,
                     false),
    DEFINE_PROP_UINT64("clock-frequency", struct STM32F2XXTimerState,
                       freq_hz, 1000000000),
};

static void stm32f2xx_timer_init(Object *obj)
{
    STM32F2XXTimerState *s = STM32F2XXTIMER(obj);

    sysbus_init_irq(SYS_BUS_DEVICE(obj), &s->irq);
    sysbus_init_irq(SYS_BUS_DEVICE(obj), &s->cc_irq);

    memory_region_init_io(&s->iomem, obj, &stm32f2xx_timer_ops, s,
                          "stm32f2xx_timer", 0x400);
    sysbus_init_mmio(SYS_BUS_DEVICE(obj), &s->iomem);
}

static void stm32f2xx_timer_realize(DeviceState *dev, Error **errp)
{
    STM32F2XXTimerState *s = STM32F2XXTIMER(dev);
    s->timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, stm32f2xx_timer_interrupt, s);
    s->cc_timer = timer_new_ns(QEMU_CLOCK_VIRTUAL,
                               stm32f2xx_timer_cc_interrupt, s);
}

static void stm32f2xx_timer_class_init(ObjectClass *klass, const void *data)
{
    DeviceClass *dc = DEVICE_CLASS(klass);

    device_class_set_legacy_reset(dc, stm32f2xx_timer_reset);
    device_class_set_props(dc, stm32f2xx_timer_properties);
    dc->vmsd = &vmstate_stm32f2xx_timer;
    dc->realize = stm32f2xx_timer_realize;
}

static const TypeInfo stm32f2xx_timer_info = {
    .name          = TYPE_STM32F2XX_TIMER,
    .parent        = TYPE_SYS_BUS_DEVICE,
    .instance_size = sizeof(STM32F2XXTimerState),
    .instance_init = stm32f2xx_timer_init,
    .class_init    = stm32f2xx_timer_class_init,
};

static void stm32f2xx_timer_register_types(void)
{
    type_register_static(&stm32f2xx_timer_info);
}

type_init(stm32f2xx_timer_register_types)
