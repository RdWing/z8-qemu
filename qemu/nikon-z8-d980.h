/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright (C) 2026 RdWing */
/* Functional external Bayer writer for the observed D980 mode2 profile.
 * Packed12 little-endian pairs and CFA-cell resampling are explicit lab
 * assumptions. Native format2/stride values alone do not prove the physical
 * wire packing, optical margins or actual sensor precision. */
static void primary_d980_input_trace(NikonZ8State *s, const char *action, uint32_t previous, uint32_t value);
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

static bool primary_d980_descriptor_ready(NikonZ8State *s, const uint32_t *c)
{
    unsigned w, h, pitch;
    uint64_t encoded, physical;
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

static bool primary_d980_ready(NikonZ8State *s)
{
    return primary_d980_descriptor_ready(s, s->primary_d980_latched);
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
    if (video_raw_descriptor(s)) {
        if (single_input) { return false; }
        if (s->video_secondary_parallel_model) {
            /* Both configured consumers see this source-clock input. Neither
             * admission retires or overwrites the other's pending output. */
            bool packet=video_raw_receive(s);
            bool sensor=video_secondary_sensor_receive(s);
            return packet || sensor;
        }
        return video_secondary_sensor_receive(s) || video_raw_receive(s);
    }
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
    engine153_deferred_try(s);
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
    s->primary_d980_single_submit = s->primary_d980_latched_submit;
    s->primary_d980_single_frames++;
    if (s->z8_still) {
        /* Functional still input: publish upper bit6 after all DMA bytes
         * and retain the inherited +14 bit0 input. C3.11 getter40c1f038
         * reads both +10/+14 low bits; that software contract alone does
         * not establish this field as a physical capture-frame marker. */
        s->engine150c_bit6_pending |= 0x40;
        s->engine_150c_primary[0x14 / 4] |= 1;
        s->z8_still_ends++;
        engine150c_stop_irq_update(s);
    }
    primary_d980_input_trace(s, "dma", 0, 0);
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
    /* The finite input can finish with the preview clock stopped.
     * Complete every actual pixel/source/channel write first, then
     * latch only bit6's finite-frame notification. The original mask,
     * ISR/W1C and deferred drain still own its delivery/retirement.
     * Diagnostic bit2 remains an independent cycle-clock input. */
    if (s->primary_reset_queued_start_model) { engine150c_bit6_pulse(s); }
    if (s->primary_d980_single_timer) { timer_del(s->primary_d980_single_timer); }
}

/* Original MAIN/EX starts finite SIF input independently of preview channel0.
 * Bind the observed source-group rising edge to this armed descriptor's enable
 * generation. The external Bayer writer and pacing remain functional models. */
static bool primary_d980_native_single_owner(NikonZ8State *s)
{
    return s->native_mcu && s->z8_still && s->z8_timed_single_model &&
           s->primary_d980_single_model && s->primary_d980_single_armed &&
           s->primary_d980_input_epoch &&
           s->primary_d980_single_request_epoch == s->primary_d980_input_epoch &&
           !s->primary_reset_stage && s->engine150c_active == 0x401e &&
           !video_raw_descriptor(s);
}

static bool primary_d980_native_source_config(NikonZ8State *s)
{
    /* First still and a still after reset/recovery, respectively. Neither
     * has the preview RAW-input bit9; the original finite START is separate. */
    return s->event_control_1508[3] == 0x4000 ||
           s->event_control_1508[3] == 0x7009;
}

static bool primary_d980_single_source_ready(NikonZ8State *s)
{
    return (s->event_control_1508[3] & 0x201) == 0x201 ||
           (primary_d980_native_single_owner(s) &&
            s->primary_d980_source_start_epoch == s->primary_d980_input_epoch &&
            (s->event_control_1508[0] & 1) &&
            primary_d980_native_source_config(s) && !s->event_mode_1508[0]);
}

static void primary_d980_source_control(NikonZ8State *s, unsigned group,
                                        uint32_t previous, uint32_t value)
{
    if (group || !primary_d980_native_single_owner(s)) { return; }
    if (!(previous & 1) && (value & 1) &&
        primary_d980_native_source_config(s) && !s->event_mode_1508[0]) {
        s->primary_d980_source_start_epoch = s->primary_d980_input_epoch;
        primary_d980_input_trace(s, "source-start", previous, value);
    } else if ((previous & 1) && !(value & 1) &&
               s->primary_d980_source_start_epoch == s->primary_d980_input_epoch) {
        primary_d980_single_cancel(s);
    }
}

/* Explicit live-single experiment: the normal preparation branch starts
 * SIF before enabling the finite full-resolution descriptor. Consume one
 * later source-clock frame for that fresh owner, rather than inventing a
 * second START edge or changing its channel bitmap. The observed JPEG and RAW
 * descriptors use packed12 and packed14 respectively; each retains its exact
 * pitch. Their source timing and physical packing remain model hypotheses. */
static bool primary_d980_native_live_source(NikonZ8State *s)
{
    const uint32_t *c = s->primary_d980_latched;
    return s->primary_d980_live_single_model && s->native_mcu && s->z8_still &&
           s->z8_timed_single_model && s->primary_d980_single_model &&
           s->primary_d980_single_armed && s->primary_d980_input_epoch &&
           s->primary_d980_single_request_epoch == s->primary_d980_input_epoch &&
           !s->primary_reset_stage && s->engine150c_active == 0x77f7f &&
           s->event_timing_active && (s->event_control_1508[0] & 1) &&
           s->event_control_1508[3] == 0x704b && !s->event_mode_1508[0] &&
           c[1] == (8280u << 16) && c[2] == (5520u << 16) &&
           ((c[0] == 2 && c[4] == 12448) ||
            (c[0] == 1 && c[4] == 14496)) &&
           !video_raw_descriptor(s) && primary_d980_ready(s);
}

/* Z8 timing hypothesis: periodic input may own an armed single request.
 * Complete only after primary_d980_receive writes the full frame; an armed
 * request or a source-ready bitmap alone is not a completion event. */
static void primary_d980_tick(NikonZ8State *s)
{
    if (s->z8_timed_single_model && s->primary_d980_single_armed) {
        bool live_source = primary_d980_native_live_source(s);
        if ((s->event_control_1508[3] & 0x201) != 0x201 && !live_source) {
            return;
        }
        if (live_source && ++s->primary_d980_single_attempts > 64) {
            primary_d980_single_cancel(s);
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
    /* Z6III finite still input owns its own tick. A native movie FIFO
     * descriptor instead consumes the continuous source clock. */
    if (s->z8_still && !video_raw_descriptor(s)) { return; }
    if (!primary_d980_finite_input_owned(s)) { primary_d980_receive(s, false); }
}

/* Admission diagnostics describe real device ownership, never a completion.
 * Native630 loses the third finite request before RAW production; retain the
 * small control transition sequence so reset and front ordering can be
 * compared without dumping image buffers or stopping the original CPU. */
static void primary_d980_input_trace(NikonZ8State *s, const char *action,
                                     uint32_t previous, uint32_t value)
{
    if (!s->primary_d980_single_model) { return; }
    fprintf(stderr, "Z8_D980_INPUT action=%s ns=%" PRId64 " pc=%" PRIx64
        " previous=%x value=%x prepared=%u armed=%u epoch=%" PRIu64
        " completed=%" PRIu64 " frames=%" PRIu64 " primary=%x reset=%u"
        " clock=%u live=%u control=%x front=%x submits=%" PRIu64
        " completed_submit=%" PRIu64 " rearms=%" PRIu64 "\n", action,
        qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL),
        current_cpu ? ARM_CPU(current_cpu)->env.pc : 0, previous, value,
        s->primary_d980_prepared, s->primary_d980_single_armed,
        s->primary_d980_input_epoch, s->primary_d980_single_epoch,
        s->primary_d980_frames, s->engine150c_active, s->primary_reset_stage,
        s->event_timing_active, s->primary_d980_live_single_model,
        s->event_control_1508[3], s->event_mode_1508[0],
        s->primary_d980_submits, s->primary_d980_single_submit,
        s->primary_d980_live_rearms);
}

static void primary_d980_single_cancel(NikonZ8State *s)
{
    if (s->primary_d980_prepared || s->primary_d980_single_armed) {
        primary_d980_input_trace(s, "cancel", 0, 0);
    }
    s->primary_capture_deferred = false;
    s->primary_d980_prepare_cancelled += s->primary_d980_prepared;
    s->primary_d980_prepared = false;
    s->primary_d980_single_cancelled += s->primary_d980_single_armed;
    s->primary_d980_single_armed = false;
    s->primary_d980_source_start_epoch = 0;
    if (s->primary_d980_single_timer) { timer_del(s->primary_d980_single_timer); }
}

static void primary_d980_single_tick(void *opaque)
{
    NikonZ8State *s = opaque;
    if (!s->primary_d980_single_armed) { return; }
    if (s->primary_reset_stage || !(s->engine150c_active & 0x4000) ||
        (s->event_timing_active && !s->primary_d980_live_single_model && !s->z8_still && !s->z8_timed_single_model)) {
        primary_d980_single_cancel(s);
        return;
    }
    /* FRONT preparation precedes source START. Original MAIN/EX can enable
     * bitmap201 after more than 64 timer polls. A poll before readiness is
     * not a DMA attempt: retain this request until START or original stop/
     * reset. Keep the 64-attempt bound for an admitted source that refuses
     * data. Neither waiting nor admission writes pixels or completes IRQs. */
    if (!primary_d980_single_source_ready(s)) {
        s->primary_d980_single_source_waits++;
        timer_mod(s->primary_d980_single_timer,
                  qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 33333333);
        return;
    }
    if (++s->primary_d980_single_attempts > 64) {
        primary_d980_single_cancel(s);
        return;
    }
    if (s->z8_timed_single_model && s->event_timing_active &&
        !(primary_d980_native_single_owner(s) &&
          s->primary_d980_source_start_epoch == s->primary_d980_input_epoch)) {
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
    if (primary_d980_single_source_ready(s) && primary_d980_receive(s, true)) {
        primary_d980_single_complete(s);
        return;
    }
    timer_mod(s->primary_d980_single_timer,
              qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 33333333);
}

static void primary_d980_single_arm(NikonZ8State *s)
{
    s->primary_d980_single_armed = true;
    s->primary_d980_single_request_epoch = s->primary_d980_input_epoch;
    s->primary_d980_single_attempts = 0;
    s->primary_d980_single_requests++;
    primary_d980_input_trace(s, "arm", 0, 0);
    timer_mod(s->primary_d980_single_timer,
              qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 33333333);
}

/* Explicit native live-HE continuation: C3.11 resubmits the input table
 * while the shared preview unit remains enabled. A later FRONT preparation
 * may own that fresh submission only after the previous finite HE transaction
 * has retired. Latch/arm here, never DMA or completion. This input-generation
 * boundary is a functional model, not measured silicon latch timing. */
static bool primary_d980_live_rearm(NikonZ8State *s)
{
    if (!s->primary_d980_live_single_model || !s->native_mcu || !s->z8_still ||
        !s->z8_timed_single_model || !s->primary_d980_single_model ||
        s->primary_d980_single_armed || s->primary_d980_prepared ||
        !s->primary_d980_input_epoch ||
        s->primary_d980_input_epoch != s->primary_d980_single_epoch ||
        !s->primary_d980_single_submit ||
        s->primary_d980_submits <= s->primary_d980_single_submit ||
        s->primary_reset_stage || s->engine150c_stop_requested ||
        s->engine150c_stop_reset_asserted || s->engine150c_active != 0x77f7f ||
        !s->event_timing_active || !(s->event_control_1508[0] & 1) ||
        s->event_control_1508[3] != 0x724b || video_raw_descriptor(s) ||
        !s->engine152c_he_still_model || !s->engine152c_he_jobs ||
        s->engine152c_he_jobs != s->primary_d980_single_frames ||
        s->engine152c_he_acks != s->engine152c_he_jobs ||
        s->engine152c_he_stop_acks != s->engine152c_he_jobs ||
        s->engine152c_he_pending || s->engine152c_request_pending ||
        s->engine152c_he_stop_pending || s->engine152c_stream_requested ||
        s->engine152c_stream_pending ||
        (s->primary_d980_pending & ~0x4000000u) ||
        (s->primary_d980_pending & s->engine_150c_init[0x20c / 4]) ||
        !primary_d980_descriptor_ready(s, s->primary_d980_submitted)) {
        return false;
    }
    memcpy(s->primary_d980_latched, s->primary_d980_submitted,
           sizeof(s->primary_d980_latched));
    s->primary_d980_latched_submit = s->primary_d980_submits;
    s->primary_d980_slot = 0;
    /* The old masked done bit owns no enabled IRQ. Reinitialize the writer
     * status as on its existing fresh-enable path, without an ISR ACK. */
    s->primary_d980_pending = 0;
    s->primary_d980_input_epoch++;
    s->primary_d980_live_rearms++;
    primary_d980_input_trace(s, "rearm", 0, 0);
    return true;
}

static void primary_d980_single_mode(NikonZ8State *s, unsigned channel,
                                    uint32_t previous, uint32_t value)
{
    if (!channel && previous != value) {
        primary_d980_input_trace(s, "front", previous, value);
    }
    if (!s->primary_d980_single_model || channel || previous != 2 || value != 3 ||
        s->primary_reset_stage || (s->event_timing_active && !s->primary_d980_live_single_model && !s->z8_still && !s->z8_timed_single_model)) {
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
    primary_d980_live_rearm(s);
    if (!s->primary_d980_input_epoch ||
        s->primary_d980_single_epoch == s->primary_d980_input_epoch ||
        s->primary_d980_single_armed) {
        return;
    }
    primary_d980_single_arm(s);
}
