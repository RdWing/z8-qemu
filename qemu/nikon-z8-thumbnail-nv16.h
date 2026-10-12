/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright (C) 2026 RdWing */
/* Native-derived A2 RAM -> B4/F4; functional nearest NV16, no physical ISP.
 * Only current owned capture output1/2 may supply a finite request. */
static bool capture_thumbnail_prepare(NikonZ8State *s)
{
    const uint32_t *a = s->engine1542_config[2];
    const uint32_t *b = s->engine1542_config[7];
    const uint32_t *f = s->engine1542_config[19];
    unsigned w = a[0x4c / 4], h = a[0x50 / 4], pitch = a[0x38 / 4];
    unsigned ow = f[0x2c / 4], oh = f[0x30 / 4], op = b[0x38 / 4];
    uint64_t y = capture_nv16_address(a, 0x20), uv = capture_nv16_address(a, 0x28);
    uint64_t p[4] = { y, uv, capture_nv16_address(b, 0x20), capture_nv16_address(b, 0x28) };
    uint64_t n[4] = { (uint64_t)pitch * h, (uint64_t)pitch * h, (uint64_t)op * oh, (uint64_t)op * oh };
    int owner = -1;
    if (!s->capture_nv16_jobs || s->capture_thumbnail_consumed_nv16 == s->capture_nv16_jobs ||
        a[8 / 4] != 0x10000000 || b[0xc / 4] != 0x41000010 || b[0x10 / 4] != 1 ||
        b[0x40 / 4] != 0x22 || b[0x3c / 4] != op ||
        (f[0] != 2 && f[0] != 4) || (f[1] != 1 && f[1] != 4) ||
        f[0x18 / 4] != w || f[0x1c / 4] != h || f[0x24 / 4] || f[0x28 / 4] ||
        !ow || (ow & 1) || ow > 16384 || !oh || oh > 8192 || op < ow || op > 32768 ||
        !f[0x10 / 4] || !f[0x14 / 4] || f[0x20 / 4] > 7 ||
        capture_nv16_coordinate(f, ow - 1, false) >= w ||
        capture_nv16_coordinate(f, oh - 1, true) >= h) { return false; }
    for (unsigned j = 1; j < 3; j++) {
        if (y == s->capture_nv16_y[j] && uv == s->capture_nv16_uv[j] &&
            w == s->capture_nv16_w[j] && h == s->capture_nv16_h[j] &&
            pitch == s->capture_nv16_stride[j]) { owner = j; }
    }
    if (owner < 0) { return false; }
    for (unsigned j = 0; j < 4; j++) {
        if (!capture_nv16_span(s, p[j], n[j])) { return false; }
        for (unsigned k = 0; k < j; k++) {
            if (p[j] < p[k] + n[k] && p[k] < p[j] + n[j]) { return false; }
        }
    }
    memcpy(s->capture_thumbnail_output, b, sizeof(s->capture_thumbnail_output));
    memcpy(s->capture_thumbnail_geometry, f, sizeof(s->capture_thumbnail_geometry));
    s->capture_thumbnail_source_owner = owner;
    s->capture_thumbnail_requests++;
    return true;
}

static void capture_thumbnail_run(NikonZ8State *s)
{
    const uint32_t *a = s->engine1542_ram_input_latched;
    const uint32_t *b = s->capture_thumbnail_output, *f = s->capture_thumbnail_geometry;
    unsigned h = a[0x50 / 4], pitch = a[0x38 / 4];
    unsigned ow = f[0x2c / 4], oh = f[0x30 / 4], op = b[0x38 / 4];
    size_t source_n = (size_t)pitch * h, target_n = (size_t)op * oh;
    uint64_t y = capture_nv16_address(a, 0x20), uv = capture_nv16_address(a, 0x28);
    uint64_t ty = capture_nv16_address(b, 0x20), tuv = capture_nv16_address(b, 0x28);
    uint8_t *input = g_malloc(source_n * 2), *output = g_malloc(target_n * 2);
    bool ok = address_space_read(&address_space_memory, y, MEMTXATTRS_UNSPECIFIED, input, source_n) == MEMTX_OK &&
        address_space_read(&address_space_memory, uv, MEMTXATTRS_UNSPECIFIED, input + source_n, source_n) == MEMTX_OK;
    memset(output, 0, target_n); memset(output + target_n, 128, target_n);
    /* Build all visible bytes before any write or input-boundary event.
     * The declared nearest convention matches the existing functional stream
     * model; it is not a reverse-engineered Nikon physical filter. */
    for (unsigned r = 0; ok && r < oh; r++) {
        unsigned sy = capture_nv16_coordinate(f, r, true);
        for (unsigned x = 0; x < ow; x++) {
            unsigned sx = capture_nv16_coordinate(f, x, false);
            output[(size_t)r * op + x] = input[(size_t)sy * pitch + sx];
        }
        for (unsigned x = 0; x < ow; x += 2) {
            unsigned sx = capture_nv16_coordinate(f, x, false) & ~1u;
            output[target_n + (size_t)r * op + x] = input[source_n + (size_t)sy * pitch + sx];
            output[target_n + (size_t)r * op + x + 1] = input[source_n + (size_t)sy * pitch + sx + 1];
        }
    }
    if (ok) {
        ok = address_space_write(&address_space_memory, ty, MEMTXATTRS_UNSPECIFIED, output, target_n) == MEMTX_OK &&
            address_space_write(&address_space_memory, tuv, MEMTXATTRS_UNSPECIFIED, output + target_n, target_n) == MEMTX_OK;
    }
    g_free(input); g_free(output);
    if (!ok) { s->capture_thumbnail_failed = true; return; }
    s->capture_thumbnail_jobs++; s->capture_thumbnail_bytes += target_n * 2;
    s->capture_thumbnail_input_bytes += source_n * 2;
    s->capture_thumbnail_consumed_nv16 = s->capture_nv16_jobs;
    s->capture_thumbnail_y = ty; s->capture_thumbnail_uv = tuv;
    s->capture_thumbnail_w = ow; s->capture_thumbnail_h = oh; s->capture_thumbnail_stride = op;
    /* Original native512 succeeds and ACKs without an explicit input stop.
     * The finite data job has finished both writes. Retire internal busy
     * before IRQ; preserve command/snapshot and pending W1C ownership. */
    s->engine1542_ram_input_active = false;
    /* Native511 direct RAM worker waits on A2 input end; C2 is not started.
     * Functional combined first/last input boundaries only after both writes.
     * Do not synthesize C2/B4 completions or write original task flags. */
    s->engine1542_pending[2] |= 0x11;
    raw_pipeline_irq_update(s);
    fprintf(stderr, "Z8_THUMBNAIL_NV16 job=%" PRIu64 " input=%" PRIx64 "/%" PRIx64
        " output=%" PRIx64 "/%" PRIx64 " geometry=%ux%u stride=%u; actual owned RAM\n",
        s->capture_thumbnail_jobs, y, uv, ty, tuv, ow, oh, op);
}

static bool get_capture_thumbnail_model(Object *obj, Error **errp)
{ return NIKON_Z8_LAB(obj)->capture_thumbnail_model; }

static void set_capture_thumbnail_model(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    if (s->image_ram.ram || s->image_ram.rom_device) {
        error_setg(errp, "capture-thumbnail-nv16-model is immutable after realization"); return;
    }
    s->capture_thumbnail_model = value;
}

static char *get_capture_thumbnail_state(Object *obj, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    return g_strdup_printf("{\"enabled\":%s,\"failed\":%s,\"requests\":%" PRIu64 ",\"jobs\":%" PRIu64
        ",\"bytes\":%" PRIu64 ",\"input_bytes\":%" PRIu64 ",\"consumed_nv16_job\":%" PRIu64
        ",\"source_owned_output\":%u,\"y\":%" PRIu64 ",\"uv\":%" PRIu64
        ",\"width\":%u,\"height\":%u,\"stride\":%u,\"input_pending\":%u,"
        "\"physical_algorithm_verified\":false,\"native_file_saved\":false,"
        "\"scope\":\"owned small/mid NV16 RAM through original A2/B4/F4 finite parameters, functional nearest and combined input boundaries; no physical filter/timing or camera file\"}",
        s->capture_thumbnail_model ? "true" : "false", s->capture_thumbnail_failed ? "true" : "false",
        s->capture_thumbnail_requests, s->capture_thumbnail_jobs, s->capture_thumbnail_bytes,
        s->capture_thumbnail_input_bytes, s->capture_thumbnail_consumed_nv16, s->capture_thumbnail_source_owner,
        s->capture_thumbnail_y, s->capture_thumbnail_uv, s->capture_thumbnail_w, s->capture_thumbnail_h,
        s->capture_thumbnail_stride, s->engine1542_pending[2]);
}
