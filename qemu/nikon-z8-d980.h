/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright (C) 2026 RdWing */
/* Functional external Bayer writer for the observed D980 mode2 profile.
 * Packed12 little-endian pairs and CFA-cell resampling are explicit lab
 * assumptions. Native format2/stride values alone do not prove the physical
 * wire packing, optical margins or actual sensor precision. */
static bool primary_d980_description(NikonZ8State *s, const uint32_t *c,
    unsigned slot, unsigned *width, unsigned *height, unsigned *stride,
    uint64_t *encoded, uint64_t *physical)
{
    *width = c[1] >> 16;
    *height = c[2] >> 16;
    *stride = c[4];
    unsigned bank = c[7];
    unsigned bits = c[0] == 1 && s->primary_d980_packed14_model ? 14 : 12;
    if (!s->raw_pixels || (c[0] != 2 && !(c[0] == 1 && s->primary_d980_packed14_model)) || (c[1] & 0xffff) || (c[2] & 0xffff) ||
        !*width || !*height || ((*width | *height) & 1) ||
        *width > NIKON_RAW_MAX_DIMENSION || *height > NIKON_RAW_MAX_DIMENSION ||
        (uint64_t)*width * *height > NIKON_RAW_MAX_SAMPLES ||
        *stride != ((((*width * bits + 7) / 8) + 31) & ~31u) ||
        (uint64_t)*stride * *height > 128 * MiB ||
        c[3] || c[5] != 1 || c[6] != 1 || c[8] != 1 || c[9] || c[10] || c[11] ||
        bank > 1 || slot > 3) {
        return false;
    }
    unsigned word = 12 + bank * 8 + slot * 2;
    *encoded = c[word] | ((uint64_t)c[word + 1] << 32);
    if (*encoded & 31) { return false; }
    return raw_pipeline_address(s, *encoded, (uint64_t)*stride * *height, physical);
}

static bool primary_d980_ready(NikonZ8State *s)
{
    unsigned w, h, pitch;
    uint64_t encoded, physical;
    const uint32_t *c = s->primary_d980_latched;
    if (!primary_d980_description(s, c, 0, &w, &h, &pitch, &encoded, &physical)) {
        return false;
    }
    unsigned bank = c[7];
    for (unsigned slot = 1; slot < 4; slot++) {
        unsigned word = 12 + bank * 8 + slot * 2;
        if ((c[word] || c[word + 1]) &&
            !primary_d980_description(s, c, slot, &w, &h, &pitch, &encoded, &physical)) {
            return false;
        }
    }
    return true;
}

static uint8_t *primary_d980_pack12(const NikonRawPixels *p,
                                  unsigned width, unsigned height, unsigned stride)
{
    uint8_t *pixels = g_malloc0((size_t)stride * height);
    for (unsigned y = 0; y < height; y++) {
        unsigned sy = ((uint64_t)(y / 2) * (p->height / 2) / (height / 2)) * 2 + (y & 1);
        uint8_t *row = pixels + (size_t)y * stride;
        for (unsigned x = 0; x < width; x += 2) {
            unsigned sx = ((uint64_t)(x / 2) * (p->width / 2) / (width / 2)) * 2;
            uint16_t a = MIN(4095, ((uint64_t)p->samples[(size_t)sy * p->width + sx] * 4095 + p->white / 2) / p->white);
            uint16_t b = MIN(4095, ((uint64_t)p->samples[(size_t)sy * p->width + sx + 1] * 4095 + p->white / 2) / p->white);
            unsigned off = x * 3 / 2;
            row[off] = a;
            row[off + 1] = (a >> 8) | ((b & 15) << 4);
            row[off + 2] = b >> 4;
        }
    }
    return pixels;
}

/* Little-endian contiguous14-bit groups are an explicit lab hypothesis.
 * The native mode1 and pitch alone do not establish physical wire packing. */
static uint8_t *primary_d980_pack14(const NikonRawPixels *p,
                                  unsigned width, unsigned height, unsigned stride)
{
    uint8_t *pixels = g_malloc0((size_t)stride * height);
    for (unsigned y = 0; y < height; y++) {
        unsigned sy = ((uint64_t)(y / 2) * (p->height / 2) / (height / 2)) * 2 + (y & 1);
        uint8_t *row = pixels + (size_t)y * stride;
        for (unsigned x = 0; x < width; x += 4) {
            unsigned count = MIN(4, width - x);
            uint64_t packed = 0;
            for (unsigned j = 0; j < count; j++) {
                unsigned sx = ((uint64_t)((x + j) / 2) * (p->width / 2) / (width / 2)) * 2 + ((x + j) & 1);
                uint16_t value = MIN(16383, ((uint64_t)p->samples[(size_t)sy * p->width + sx] * 16383 + p->white / 2) / p->white);
                packed |= (uint64_t)value << (j * 14);
            }
            for (unsigned byte = 0; byte < (count * 14 + 7) / 8; byte++) {
                row[x * 14 / 8 + byte] = packed >> (byte * 8);
            }
        }
    }
    return pixels;
}

static bool primary_d980_receive(NikonZ8State *s, bool single_input)
{
    if (!s->primary_d980_stream_model || (!single_input && !s->event_timing_active) ||
        s->primary_reset_stage || !(s->engine150c_active & 0x4000) ||
        (s->engine_150c_init[0x18 / 4] & 0x4000) || s->primary_d980_pending) {
        return false;
    }
    unsigned w, h, pitch, slot = s->primary_d980_slot;
    uint64_t encoded, physical;
    /* The native descriptor has four slots; only nonzero submitted slots
     * participate. Slot cycling is a functional model, not chip timing. */
    unsigned bank = s->primary_d980_latched[7];
    if (!s->primary_d980_latched[12 + bank * 8 + slot * 2] &&
        !s->primary_d980_latched[13 + bank * 8 + slot * 2]) {
        slot = 0;
    }
    if (!primary_d980_description(s, s->primary_d980_latched, slot,
                                 &w, &h, &pitch, &encoded, &physical)) {
        s->primary_d980_rejects++;
        unknown_access(s, 0x150d9800, s->primary_d980_latched[0], 4, true);
        return false;
    }
    if (!s->primary_d980_cache || w != s->primary_d980_cache_width ||
        h != s->primary_d980_cache_height || pitch != s->primary_d980_cache_stride || s->primary_d980_latched[0] != s->primary_d980_cache_format) {
        g_free(s->primary_d980_cache);
        s->primary_d980_cache = s->primary_d980_latched[0] == 1 ?
            primary_d980_pack14(s->raw_pixels, w, h, pitch) :
            primary_d980_pack12(s->raw_pixels, w, h, pitch);
        s->primary_d980_cache_width = w;
        s->primary_d980_cache_height = h;
        s->primary_d980_cache_stride = pitch;
        s->primary_d980_cache_format = s->primary_d980_latched[0];
    }
    size_t bytes = (size_t)pitch * h;
    if (address_space_write(&address_space_memory, physical, MEMTXATTRS_UNSPECIFIED,
                            s->primary_d980_cache, bytes) != MEMTX_OK) {
        s->primary_d980_rejects++;
        unknown_access(s, 0x150d9920, encoded, 4, true);
        return false;
    }
    s->primary_d980_frames++;
    s->primary_d980_bytes += bytes;
    s->primary_d980_last_encoded = encoded;
    s->primary_d980_last_physical = physical;
    s->primary_d980_slot = (slot + 1) & 3;
    /* Z8 original40caf3ec and ZR40eb8e18 map logical4000 to
     * primary group1 bit26. Publish only after every output byte exists. */
    s->primary_d980_pending = 0x4000000;
    engine150c_stop_irq_update(s);
    return true;
}

/* Complete only after primary_d980_receive has written every byte. */
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

static void primary_d980_single_cancel(NikonZ8State *s)
{
    if (s->primary_d980_prepared || s->primary_d980_single_armed) fprintf(stderr,"Z8_PREP_CANCEL single-cancel pc=%" PRIx64 " lr=%" PRIx64 " prepared=%d armed=%d\n",current_cpu?ARM_CPU(current_cpu)->env.pc:0,current_cpu?ARM_CPU(current_cpu)->env.xregs[30]:0,s->primary_d980_prepared,s->primary_d980_single_armed);
    s->primary_d980_prepare_cancelled += s->primary_d980_prepared;
    s->primary_d980_prepared = false;
    s->primary_d980_single_cancelled += s->primary_d980_single_armed;
    s->primary_d980_single_armed = false;
    if (s->primary_d980_single_timer) { timer_del(s->primary_d980_single_timer); }
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

static void primary_d980_single_arm(NikonZ8State *s)
{
    s->primary_d980_single_armed = true;
    s->primary_d980_single_attempts = 0;
    s->primary_d980_single_requests++;
    timer_mod(s->primary_d980_single_timer,
              qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 33333333);
}

static void primary_d980_single_mode(NikonZ8State *s, unsigned channel,
                                    uint32_t previous, uint32_t value)
{
    if (!s->primary_d980_single_model || channel || previous != 2 || value != 3 ||
        s->primary_reset_stage || s->event_timing_active) {
        return;
    }
    if (!(s->engine150c_active & 0x4000)) {
        if (s->primary_d980_prepared_start_model && s->primary_reset_count &&
            !s->primary_d980_prepared && !s->primary_d980_single_armed) {
            fprintf(stderr,"Z8_PREP_SET pc=%" PRIx64 " lr=%" PRIx64 " units=%x\n",current_cpu?ARM_CPU(current_cpu)->env.pc:0,current_cpu?ARM_CPU(current_cpu)->env.xregs[30]:0,s->engine150c_active);
            s->primary_d980_prepared = true;
            s->primary_d980_prepare_requests++;
        }
        return;
    }
    if (!s->primary_d980_input_epoch ||
        s->primary_d980_single_epoch == s->primary_d980_input_epoch ||
        s->primary_d980_single_armed) {
        return;
    }
    primary_d980_single_arm(s);
}
