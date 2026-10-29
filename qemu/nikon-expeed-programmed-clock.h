/* Copyright (C) 2026 RdWing: Z8 adaptation. */
/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Functional programmed-channel waveform from the explicit source clock.
 * Native drivers register fifteen distinct channel callbacks and commit
 * independent configuration. This implements the observed 06011000/20 and 00011000/20 mode
 * class at one edge per explicit source period. The parameter units, waveform
 * phases and physical timing are not established. No image completion, DMA,
 * application notification or firmware address is selected here.
 * Channels zero and one retain their existing independent producers.
 */

static uint32_t programmed_clock_configured_mask(NikonZ8State *s)
{
    uint32_t mask = 0;
    for (unsigned ch = 2; ch < 15; ch++) {
        const uint32_t *c = s->event_active_1508[ch];
        /* Mode bit5 is retained as an opaque variant, not interpreted as an
         * enable. The original MMIO channel/group controls supply enable.
         * Only a fully committed, observed waveform class is admitted. */
        uint32_t mode = c[7] & ~UINT32_C(0x20);
        if ((mode == 0x06011000 || mode == 0x00011000) &&
            c[0] && c[1] && c[4] && c[5]) {
            mask |= 1u << ch;
        }
    }
    return mask;
}

static uint32_t programmed_clock_armed_mask(NikonZ8State *s)
{
    if (!s->event_programmed_clock_model || !s->bootstrap_fixtures ||
        !s->event1508_channel_model || !s->event1508_timing_model ||
        !s->event_timing_active) {
        return 0;
    }
    return programmed_clock_configured_mask(s) & s->event_control_1508[3] &
           s->event_output_group_running;
}

static void programmed_clock_tick(NikonZ8State *s)
{
    uint32_t armed = programmed_clock_armed_mask(s);
    for (unsigned ch = 2; ch < 15; ch++) {
        uint32_t bit = 1u << ch;
        if (!(armed & bit)) {
            continue;
        }
        s->event_programmed_clock_ticks[ch]++;
        if (s->event_pending_1508 & bit) {
            s->event_programmed_clock_coalesced[ch]++;
        } else {
            s->event_pending_1508 |= bit;
            s->event_programmed_clock_events[ch]++;
        }
    }
    /* The caller updates the existing fifteen-slot IRQ after all clock
     * causes are ready. Masks only hide pending; its own W1C releases it. */
}

static bool get_event_programmed_clock_model(Object *obj, Error **errp)
{
    return NIKON_Z8_LAB(obj)->event_programmed_clock_model;
}

static void set_event_programmed_clock_model(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    if (s->image_ram.ram || s->image_ram.rom_device) {
        error_setg(errp, "programmed channel clock is immutable after realization");
        return;
    }
    s->event_programmed_clock_model = value;
}

static char *get_event_programmed_clock_state(Object *obj, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    GString *out = g_string_new(NULL);
    g_string_append_printf(out, "{\"enabled\":%s,\"configured_mask\":%u,"
        "\"armed_mask\":%u,\"channel_control\":%u,\"group_running\":%u,"
        "\"pending\":%u,\"irq_mask\":%u,\"source_active\":%s,"
        "\"source_period_ns\":%"PRIu64",\"lanes\":[",
        s->event_programmed_clock_model ? "true" : "false",
        programmed_clock_configured_mask(s), programmed_clock_armed_mask(s),
        s->event_control_1508[3], s->event_output_group_running,
        s->event_pending_1508, s->event_mask_1508,
        s->event_timing_active ? "true" : "false", s->event_timing_period_ns);
    for (unsigned ch = 0; ch < 15; ch++) {
        g_string_append_printf(out, "%s{\"channel\":%u,\"ticks\":%"PRIu64
            ",\"events\":%"PRIu64",\"coalesced\":%"PRIu64",\"latched\":[",
            ch ? "," : "", ch, s->event_programmed_clock_ticks[ch],
            s->event_programmed_clock_events[ch], s->event_programmed_clock_coalesced[ch]);
        for (unsigned word = 0; word < 8; word++) {
            g_string_append_printf(out, "%s%u", word ? "," : "", s->event_active_1508[ch][word]);
        }
        g_string_append(out, "]}");
    }
    g_string_append(out, "],\"pixel_bytes\":0,\"physical_timing_verified\":false,"
        "\"scope\":\"functional committed waveform class at explicit source period; "
        "channel/group enable, independent pending/W1C; waveform phases unverified\"}");
    return g_string_free(out, false);
}
