/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright (C) 2026 RdWing */
#include <stdint.h>
#include <stdbool.h>
#include <stdio.h>
#include <inttypes.h>
#include <assert.h>
#define QEMU_CLOCK_VIRTUAL 0
typedef struct { uint64_t event_control_1508[4];uint64_t primary_d980_pending;
uint64_t engine150c_active;
uint64_t event_channel_inputs;
uint64_t event_pending_1508;
uint64_t event_timing_active;
uint64_t primary_d980_bytes;
uint64_t primary_d980_channel_boundaries;
uint64_t primary_d980_channel_boundary_model;
uint64_t primary_d980_channel_coalesced;
uint64_t primary_d980_frames;
uint64_t primary_d980_input_epoch;
uint64_t primary_d980_single_armed;
uint64_t primary_d980_single_attempts;
uint64_t primary_d980_single_epoch;
uint64_t primary_d980_single_frames;
uint64_t primary_d980_single_timer;
uint64_t primary_d980_source_notifications;
uint64_t primary_d980_source_notify_model;
uint64_t primary_reset_stage;
uint64_t raw_source_boundaries;
uint64_t z8_timed_single_model;
} NikonZ8State;
static int allow_dma, dma_calls, notify_calls, channel_calls, cancels;
static bool primary_d980_receive(NikonZ8State *s, bool single) {(void)single;dma_calls++;if(!allow_dma||s->primary_d980_pending)return false;s->primary_d980_pending=1;s->primary_d980_frames++;s->primary_d980_bytes+=80017920;return true;}
static void raw_source_boundary_receive(NikonZ8State *s,bool v) {(void)v;s->raw_source_boundaries++;notify_calls++;}
static void event_channel_update_irq(NikonZ8State *s) {(void)s;channel_calls++;}
static void primary_d980_single_cancel(NikonZ8State *s){s->primary_d980_single_armed=0;cancels++;}
static uint64_t qemu_clock_get_ns(int v){(void)v;return 0;}
static void timer_mod(uint64_t timer,uint64_t ns){(void)timer;(void)ns;}
static void primary_d980_single_complete(NikonZ8State *s)
{
        s->primary_d980_single_armed = false;
        s->primary_d980_single_epoch = s->primary_d980_input_epoch;
        s->primary_d980_single_frames++;
        if (s->primary_d980_source_notify_model) {
            /* Notify the existing source wait only after the complete DMA.
             * Both original callbacks map group1 bit29 to wait400000;
             * no OS wait state or ISR acknowledgement is written here. */
            uint64_t boundaries = s->raw_source_boundaries;
            raw_source_boundary_receive(s, true);
            s->primary_d980_source_notifications += s->raw_source_boundaries != boundaries;
        }
        if (s->primary_d980_channel_boundary_model) {
            /* The complete input frame precedes this existing channel clock
             * boundary. Shared channel pending/ACK semantics remain intact;
             * primary stop/reset does not acknowledge a channel on its behalf. */
            s->primary_d980_channel_boundaries++;
            s->primary_d980_channel_coalesced += !!(s->event_pending_1508 & 1);
            s->event_pending_1508 |= 1;
            s->event_channel_inputs++;
            event_channel_update_irq(s);
        }
}
static void primary_d980_tick(NikonZ8State *s)
{
    if (s->z8_timed_single_model && s->primary_d980_single_armed) {
        if ((s->event_control_1508[3] & 0x201) != 0x201) {
            return;
        }
        if (primary_d980_receive(s, false)) {
            primary_d980_single_complete(s);
            fprintf(stderr, "Z8_TIMED_SINGLE frames=%" PRIu64
                    " bytes=%" PRIu64 " epoch=%" PRIu64
                    "; periodic DMA owns pending single request\n",
                    s->primary_d980_frames, s->primary_d980_bytes,
                    s->primary_d980_single_epoch);
        }
        return;
    }
    primary_d980_receive(s, false);
}
static void primary_d980_single_tick(void *opaque)
{
    NikonZ8State *s = opaque;
    if (!s->primary_d980_single_armed) { return; }
    if (s->primary_reset_stage || !(s->engine150c_active & 0x4000) ||
        (s->event_timing_active && !s->z8_timed_single_model) || ++s->primary_d980_single_attempts > 64) {
        primary_d980_single_cancel(s);
        return;
    }
    if (s->z8_timed_single_model && s->event_timing_active) {
        /* Preserve ownership while the actual periodic source supplies data.
         * Stop/reset and the bounded attempt limit above still cancel. */
        timer_mod(s->primary_d980_single_timer,
                  qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 33333333);
        return;
    }
    /* Original460: periodic source stopped, primary4000 enabled, front
     * preparation2->3, then source bitmap200. One external frame and 33ms
     * input pacing are hypotheses, not physical exposure/readout timing.
     * A later mode0 may release preparation; only actual stop/reset cancels
     * this separate input. Never fabricate a front/status result. */
    if ((s->event_control_1508[3] & 0x201) == 0x201 &&
        primary_d980_receive(s, true)) {
        primary_d980_single_complete(s);
        return;
    }
    timer_mod(s->primary_d980_single_timer,
              qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 33333333);
}
int main(void){NikonZ8State s={0};s.z8_timed_single_model=1;s.primary_d980_single_armed=1;s.event_timing_active=1;s.engine150c_active=0x4000;s.primary_d980_input_epoch=7;s.primary_d980_source_notify_model=1;s.primary_d980_channel_boundary_model=1;
primary_d980_tick(&s);assert(dma_calls==0&&s.primary_d980_single_armed);
s.event_control_1508[3]=0x201;primary_d980_tick(&s);assert(dma_calls==1&&notify_calls==0&&channel_calls==0&&s.primary_d980_single_armed);
primary_d980_single_tick(&s);assert(cancels==0&&dma_calls==1&&s.primary_d980_single_armed);
allow_dma=1;primary_d980_tick(&s);assert(s.primary_d980_single_frames==1&&s.primary_d980_single_epoch==7&&!s.primary_d980_single_armed);assert(s.primary_d980_bytes==80017920&&notify_calls==1&&channel_calls==1&&s.event_pending_1508==1);
primary_d980_tick(&s);assert(s.primary_d980_single_frames==1&&notify_calls==1);
s.primary_d980_single_armed=1;s.primary_reset_stage=1;primary_d980_single_tick(&s);assert(cancels==1&&!s.primary_d980_single_armed);
s.primary_reset_stage=0;s.primary_d980_single_armed=1;s.z8_timed_single_model=0;primary_d980_single_tick(&s);assert(cancels==2&&!s.primary_d980_single_armed);
return 0;}
