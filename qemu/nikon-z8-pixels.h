/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright (C) 2026 RdWing */
/* Functional streaming RAW -> IMPRSZ output exploration. Run234 provides
 * A0/B0..2/F0..2 and bank0 descriptors. 40c2590c registers INTID6a.
 * Resampling, NV12/NV16 selection, ring pacing and frame bit0 are explicit
 * model assumptions; this does not emulate physical EXPEED processing. */
static void raw_pipeline_irq_update(NikonZ8State *s)
{
    uint32_t pending = 0;
    if (!s->engine1542_irq || !s->raw_pipeline_model) { return; }
    for (unsigned i = 0; i < 15; i++) {
        unsigned off = i < 10 ? 0x18 : i < 13 ? 0x10 : i == 13 ? 0x14 : 0x50;
        pending |= s->engine1542_pending[i] & s->engine1542_config[i][off / 4];
    }
    qemu_set_irq(s->engine1542_irq, pending != 0);
}

static bool raw_pipeline_address(NikonZ8State *s, uint64_t encoded,
                                 uint64_t bytes, uint64_t *physical)
{
    /* Native B register versus C ring pairs differ by0x400000000:
     * E -> A and C ->8. Already physical8/A addresses are retained. */
    if (encoded >= UINT64_C(0xc00000000) && encoded < UINT64_C(0x1000000000)) {
        encoded -= UINT64_C(0x400000000);
    }
    *physical = encoded;
    return dma_ram_range(s, encoded, bytes);
}

/* Input timing is independent of IMPRSZ destination setup. Original ZR
 * 412aa7a0 maps primary subgroup1 bit29 to source wait400000; Z8 uses the
 * same cause at410b6ae8. No OS state is written by the device. This source
 * model produces no guest DMA, resize completion or saved RAW file. */
static void raw_source_boundary_receive(NikonZ8State *s, bool single_input)
{
    if (!s->raw_source_boundary_model || !s->raw_pixels ||
        (!single_input && !s->event_timing_active) || s->primary_reset_stage) {
        return;
    }
    uint32_t active = s->engine150c_active &
        ~(s->engine150c_stop_requested | s->engine150c_stop_done |
          s->engine_150c_init[0x18 / 4]);
    uint32_t causes = ((active & 2) ? 0x20000000 : 0) |
                      ((active & 0x10000) ? 0x40000000 : 0);
    if (!causes) {
        return;
    }
    s->raw_source_boundaries++;
    s->raw_source_notifications += !!(causes & ~s->raw_source_pending);
    s->raw_source_pending |= causes;
    engine150c_stop_irq_update(s);
}

static void raw_source_boundary_tick(NikonZ8State *s)
{
    raw_source_boundary_receive(s, false);
}

static bool get_raw_source_boundary_model(Object *obj, Error **errp)
{
    return NIKON_Z8_LAB(obj)->raw_source_boundary_model;
}

static void set_raw_source_boundary_model(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    if (s->image_ram.ram || s->image_ram.rom_device) {
        error_setg(errp, "raw-source-boundary-model is immutable after realization");
        return;
    }
    s->raw_source_boundary_model = value;
}

static char *get_raw_source_boundary_state(Object *obj, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    return g_strdup_printf("{\"enabled\":%s,\"pending\":%u,\"boundaries\":%" PRIu64
        ",\"notifications\":%" PRIu64 ",\"acks\":%" PRIu64 ",\"cancelled\":%" PRIu64
        ",\"pixel_dma_bytes\":0,\"physical_timing_verified\":false}",
        s->raw_source_boundary_model ? "true" : "false", s->raw_source_pending,
        s->raw_source_boundaries, s->raw_source_notifications, s->raw_source_acks,
        s->raw_source_cancelled);
}

static void raw_pipeline_tick(void *opaque)
{
    NikonZ8State *s = opaque;
    unsigned row = s->raw_pipeline_row;
    uint64_t ys[3], uvs[3], total = 0;
    unsigned widths[3], heights[3], strides[3];
    bool halves[3];
    if (!s->raw_pipeline_model) { return; }
    timer_mod(s->raw_pipeline_timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 33333333);
    /* Stopped-source reset profile: input clock and primary source unit
     * own new pixel work. Holding/resetting primary cancels future work,
     * without acknowledging a completed downstream frame on its behalf. */
    if (s->primary_stopped_source_reset_model &&
        (s->primary_reset_stage || !(s->engine150c_active & 2) ||
         (s->engine_150c_init[0x18 / 4] & 2))) {
        return;
    }
    /* Wait for the original parameter and source-gate submissions. Holding
     * a pending frame prevents overwriting buffers before the ISR accepts it. */
    if (!s->raw_pixels || !s->engine1543_active[0] || s->engine1543_held[0] ||
        !s->engine151_active[1] || !s->engine1518[2].config[0x30 / 4] ||
        s->engine1542_pending[0] || s->engine1542_pending[10] || s->raw_primary_pending ||
        (s->raw_pipeline_1514_completion_model && (s->engine151_pending[1] & 8)) ||
        (s->raw_pipeline_151c_completion_model && (s->engine1518[2].pending & 0x08100000)) ||
        (s->event1508_global1_model && (s->event_global1_pending & 0x10))) { return; }
    /* Request the following batch separately, before its final frame.
     * The original callback wakes the frame task before storing its refill
     * byte. Combining bits0/3 can race that task on another CPU. Giving the
     * refill its own IRQ before the next frame preserves the original
     * software ordering without touching task flags or firmware code. */
    if (row == 3 && !s->raw_pipeline_refill_notified) {
        s->raw_pipeline_refill_notified = true;
        s->engine1542_pending[10] |= 8;
        raw_pipeline_irq_update(s);
        return;
    }
    /* A watermark for completed buffers may outlive the input trigger.
     * Native ZR293/295 stop that trigger at row3. Requiring another input
     * clock before requesting its next descriptor bank stranded the owner.
     * New DMA remains strictly gated by the original source control. */
    if (s->primary_stopped_source_reset_model && !s->event_timing_active) {
        return;
    }
    /* 40c26780 selects one of two banks. 40c26790/26824 then write four
     * rows at +200 + bank*200. Original40e9b928 refills the other bank
     * only after C0 bit3, via40e8b0e8. Keep batch ownership until all
     * explicit paired words arrive; a selector write precedes the table.
     * Four-frame bit3 pacing is a functional hypothesis, not chip timing. */
    const uint32_t *submitted = s->engine1542_config[10];
    unsigned bank = s->raw_pipeline_bank;
    if (row == 0 && s->raw_pipeline_wait_bank) {
        unsigned selected = submitted[2] & 1;
        if (selected != bank && s->raw_pipeline_bank_written[selected] == UINT64_MAX) {
            memcpy(&s->engine1543_latched[0][(0x200 + selected * 0x200) / 4],
                   &submitted[(0x200 + selected * 0x200) / 4], 0x200);
            s->raw_pipeline_bank_written[bank] = 0;
            bank = s->raw_pipeline_bank = selected;
            s->raw_pipeline_wait_bank = false;
        } else {
            /* Continuous capture retains the current complete table until
             * its replacement is available. 260/262's artificial stall
             * also stopped the combined input boundaries and deadlocked
             * the stream. Count reuse explicitly; do not consume partial
             * new descriptors or invent an LCD destination. */
            s->raw_pipeline_repeated_batches++;
        }
    }
    const uint32_t *ring = s->engine1543_latched[0];
    for (unsigned ch = 0; ch < 3; ch++) {
        const uint32_t *b = s->engine1542_config[3 + ch];
        const uint32_t *f = s->engine1542_config[15 + ch];
        unsigned off = (0x210 + bank * 0x200 + row * 0x80 + ch * 0x10) / 4;
        uint64_t y = ring[off] | (uint64_t)ring[off + 1] << 32;
        uint64_t uv = ring[off + 2] | (uint64_t)ring[off + 3] << 32;
        unsigned w = f[0x2c / 4], h = f[0x30 / 4], stride = b[0x38 / 4];
        bool half = !(b[0xc / 4] & 0x10);
        uint64_t ybytes = (uint64_t)stride * h, uvbytes = ybytes / (half ? 2 : 1);
        if (!w || !h || ((w | h | stride) & 1) || w > 4096 || h > 4096 ||
            stride < w || stride > 8192 || stride != b[0x3c / 4] || ybytes > 16 * MiB ||
            b[0x10 / 4] != 1 || !raw_pipeline_address(s, y, ybytes, &ys[ch]) ||
            !raw_pipeline_address(s, uv, uvbytes, &uvs[ch]) ||
            !(ys[ch] + ybytes <= uvs[ch] || uvs[ch] + uvbytes <= ys[ch])) {
            s->raw_pipeline_rejects++;
            return;
        }
        widths[ch] = w; heights[ch] = h; strides[ch] = stride; halves[ch] = half;
    }
    for (unsigned ch = 0; ch < 3; ch++) {
        unsigned w = widths[ch], h = heights[ch], stride = strides[ch];
        bool half = halves[ch];
        size_t ybytes = (size_t)stride * h, uvbytes = ybytes / (half ? 2 : 1);
        if (!s->raw_pipeline_cache[ch] || s->raw_pipeline_width[ch] != w ||
            s->raw_pipeline_height[ch] != h || s->raw_pipeline_stride[ch] != stride ||
            s->raw_pipeline_uv_half[ch] != half) {
            g_free(s->raw_pipeline_cache[ch]);
            s->raw_pipeline_cache[ch] = nikon_raw_pixels_yuv(s->raw_pixels, w, h, stride, half);
            s->raw_pipeline_width[ch] = w; s->raw_pipeline_height[ch] = h;
            s->raw_pipeline_stride[ch] = stride; s->raw_pipeline_uv_half[ch] = half;
        }
        if (!s->raw_pipeline_cache[ch] ||
            address_space_write(&address_space_memory, ys[ch], MEMTXATTRS_UNSPECIFIED,
                                s->raw_pipeline_cache[ch], ybytes) != MEMTX_OK ||
            address_space_write(&address_space_memory, uvs[ch], MEMTXATTRS_UNSPECIFIED,
                                s->raw_pipeline_cache[ch] + ybytes, uvbytes) != MEMTX_OK) {
            s->raw_pipeline_rejects++;
            return;
        }
        s->raw_pipeline_y[ch] = ys[ch]; s->raw_pipeline_uv[ch] = uvs[ch];
        total += ybytes + uvbytes;
    }
    /* Native ZR40e0db5c -> 40eac290 dispatches event410b0002.
     * Registered consumer4107eaa8 tests bit3 and wakes the stream worker;
     * bit1 only sets a generic driver flag and is ignored by that consumer.
     * Bit3 follows all actual RAW-derived plane writes. W1C owns reuse and
     * continuous mode retains its request. Physical line timing unverified. */
    if (s->raw_pipeline_1514_completion_model) {
        s->engine151_pending[1] |= 8;
        s->raw_pipeline_1514_completions++;
        engine151_update_irq(s, 1);
    }
    /* Functional combined-ISP completion after all three real Y/UV
     * transfers. Original ZR40e0ae38 W1C,40e9c8a8 and4107ae48 deliver
     * these bits to the native graph. No guest references, task flags or
     * callbacks are written. Both causes must be acknowledged before reuse.
     * Disabled masks retain status; reset cancels ownership normally.
     * Physical latency and exact silicon processing remain unverified. */
    if (s->raw_pipeline_151c_completion_model) {
        Z8Engine1518 *e = &s->engine1518[2];
        e->pending |= 0x08100000;
        e->stream_frames++;
        engine1518_update_irq(e);
    }
    s->raw_pipeline_frames++;
    s->raw_pipeline_bytes += total;
    s->raw_pipeline_row = (row + 1) & 3;
    /* The original40e94934 callback consumes A0 bits0/4 as input boundary
     * notifications, distinct from C0 output bit0. This combined functional
     * ISP completes both sides after the RAW-derived writes. It does not
     * claim physical line timing. Disabled A0 produces no source event. */
    if (s->engine1542_config[0][0x10 / 4] == 1) {
        s->engine1542_pending[0] |= 0x11;
    }
    s->engine1542_pending[10] |= 1;
    if (row == 3) {
        s->raw_pipeline_refill_notified = false;
        s->raw_pipeline_wait_bank = true;
        s->raw_pipeline_batches++;
    }
    raw_pipeline_irq_update(s);
    /* Native255 CAPTG waits in410b6c50 for the second input's boundary.
     * The original ISR supplies +210 in payload+4; PPC410b677c maps bit30
     * to flag800000, and410b6ae8 maps bit29 to flag400000. Complete these
     * two active upper paths after real output writes in this combined ISP.
     * This is a functional frame boundary, not measured physical ISP timing. */
    uint32_t primary = ((s->engine150c_active & 2) ? 0x20000000 : 0) |
                       ((s->engine150c_active & 0x10000) ? 0x40000000 : 0);
    primary &= s->engine_150c_init[0x20c / 4];
    if (primary && !s->raw_source_boundary_model) {
        s->raw_primary_pending |= primary;
        s->raw_primary_events++;
        engine150c_stop_irq_update(s);
    }
    /* Native4115a914..a974 consumes global1 bit4, dispatches the firmware's
     * current sequence event and sets its stream boundary flag. The older
     * timing-only model supplied bit7 alone. Here bit4 follows real pixels. */
    if (s->event1508_global1_model && (s->event_extended_1508[0x68 / 4] & 0x10)) {
        s->event_global1_pending |= 0x10;
        s->event_global1_inputs++;
        event_global1_update_irq(s);
    }
    if (s->raw_pipeline_frames <= 8) {
        fprintf(stderr, "Z8_RAW_PIPELINE frame=%" PRIu64 " row=%u bytes=%" PRIu64
            " Y=%" PRIx64 ":%" PRIx64 ":%" PRIx64 " bank=%u pending=%x; functional Bayer output\n",
            s->raw_pipeline_frames, row, total, ys[0], ys[1], ys[2], bank, s->engine1542_pending[10]);
    }
}

static bool get_raw_pipeline_model(Object *obj, Error **errp)
{
    return NIKON_Z8_LAB(obj)->raw_pipeline_model;
}

static void set_raw_pipeline_model(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    if (s->engine1542_irq) {
        error_setg(errp, "raw-pipeline-model is immutable after realization");
        return;
    }
    s->raw_pipeline_model = value;
}

static char *get_raw_pipeline_state(Object *obj, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    GString *out = g_string_new(NULL);
    g_string_append_printf(out, "{\"enabled\":%s,\"frames\":%" PRIu64
        ",\"bytes\":%" PRIu64 ",\"rejects\":%" PRIu64 ",\"next_row\":%u,"
        "\"primary_pending\":%u,\"primary_events\":%" PRIu64 ",\"primary_acks\":%" PRIu64 ","
        "\"bank\":%u,\"wait_bank\":%s,\"batches\":%" PRIu64 ",\"repeated_batches\":%" PRIu64 ","
        "\"input_sha256\":\"%s\",\"camera_acceptance\":false,\"outputs\":[",
        s->raw_pipeline_model ? "true" : "false", s->raw_pipeline_frames,
        s->raw_pipeline_bytes, s->raw_pipeline_rejects, s->raw_pipeline_row,
        s->raw_primary_pending, s->raw_primary_events, s->raw_primary_acks,
        s->raw_pipeline_bank, s->raw_pipeline_wait_bank ? "true" : "false", s->raw_pipeline_batches,
        s->raw_pipeline_repeated_batches,
        s->statistics_raw_sha256 ? s->statistics_raw_sha256 : "");
    for (unsigned ch = 0; ch < 3; ch++) {
        g_string_append_printf(out, "%s{\"width\":%u,\"height\":%u,\"stride\":%u,"
            "\"y\":%" PRIu64 ",\"uv\":%" PRIu64 ",\"format\":\"%s\"}",
            ch ? "," : "", s->raw_pipeline_width[ch], s->raw_pipeline_height[ch],
            s->raw_pipeline_stride[ch], s->raw_pipeline_y[ch], s->raw_pipeline_uv[ch],
            s->raw_pipeline_uv_half[ch] ? "NV12" : "NV16");
    }
    g_string_append(out, "],\"scope\":\"functional streamed Bayer, simplified ISP, input boundaries and output completion; physical sensor protocol unproved\"}");
    return g_string_free(out, false);
}

static bool get_raw_pipeline_1514_completion_model(Object *obj, Error **errp)
{
    return NIKON_Z8_LAB(obj)->raw_pipeline_1514_completion_model;
}

static void set_raw_pipeline_1514_completion_model(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    if (s->engine1542_irq) {
        error_setg(errp, "raw-pipeline-1514-completion-model is immutable after realization");
        return;
    }
    s->raw_pipeline_1514_completion_model = value;
}

static char *get_raw_pipeline_1514_completion_state(Object *obj, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    return g_strdup_printf("{\"enabled\":%s,\"completions\":%" PRIu64
        ",\"acks\":%" PRIu64 ",\"pending\":%u,\"camera_acceptance\":false,"
        "\"scope\":\"optional streaming ISP completion after real pixel DMA; physical timing unverified\"}",
        s->raw_pipeline_1514_completion_model ? "true" : "false",
        s->raw_pipeline_1514_completions, s->raw_pipeline_1514_acks,
        s->engine151_pending[1] & 8);
}

static bool get_raw_pipeline_151c_completion_model(Object *obj, Error **errp)
{
    return NIKON_Z8_LAB(obj)->raw_pipeline_151c_completion_model;
}

static void set_raw_pipeline_151c_completion_model(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    if (s->image_ram.ram || s->image_ram.rom_device) {
        error_setg(errp, "raw-pipeline-151c-completion-model is immutable after realization");
        return;
    }
    s->raw_pipeline_151c_completion_model = value;
}

static char *get_raw_pipeline_151c_completion_state(Object *obj, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    Z8Engine1518 *e = &s->engine1518[2];
    return g_strdup_printf("{\"enabled\":%s,\"completions\":%" PRIu64
        ",\"acks\":%" PRIu64 ",\"cancelled\":%" PRIu64 ",\"pending\":%u,"
        "\"scope\":\"functional combined ISP source boundary after actual pixel DMA\","
        "\"physical_timing_verified\":false}",
        s->raw_pipeline_151c_completion_model ? "true" : "false",
        e->stream_frames, e->stream_acks, e->stream_cancelled,
        e->pending & 0x08100000);
}
