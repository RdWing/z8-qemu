/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Z6III decoded NV16 RAM -> A1/F4/B4 playback route. Functional nearest
 * sampling uses the native fixed-point phases. Physical filters and timing
 * are not modelled. Only successful local JPEG decoder outputs are owned. */
static bool z8_playback_span(NikonZ8State *s, uint64_t p, uint64_t n)
{
    return n && n <= 64 * MiB && !(p & 31) && dma_ram_range(s, p, n);
}

static bool z8_playback_prepare(NikonZ8State *s)
{
    const uint32_t *a = s->engine1542_config[1];
    const uint32_t *b = s->engine1542_config[7];
    const uint32_t *f = s->engine1542_config[19];
    uint64_t p[4] = {capture_nv16_address(a, 0x20), capture_nv16_address(a, 0x28),
                    capture_nv16_address(b, 0x20), capture_nv16_address(b, 0x28)};
    unsigned w = a[0x4c/4], h = a[0x50/4], ip = a[0x38/4];
    unsigned ow = f[0x2c/4], oh = f[0x30/4], op = b[0x38/4];
    uint64_t n[4] = {(uint64_t)ip*h, (uint64_t)ip*h,
                     (uint64_t)op*oh, (uint64_t)op*oh};
    int owner = -1;
    if (!s->z8_jdec_on || s->z8_playback_requested ||
        (s->engine1542_pending[1] & 0x11) || (s->engine1542_pending[11] & 0x20) ||
        (a[1] != 0x5002 && a[1] != 0x5000) || a[2] != 0x50000000 ||
        a[3] != 0x71000010 || a[4] != 1 || a[0x40/4] != 0x22 ||
        b[0xc/4] != 0x41400010 || b[0x10/4] != 1 || b[0x40/4] != 0x22 ||
        a[0x3c/4] != ip || b[0x3c/4] != op ||
        !w || (w & 1) || w > 16384 || !h || h > 8192 || ip < w || ip > 32768 ||
        !ow || (ow & 1) || ow > 16384 || !oh || oh > 8192 || op < ow || op > 32768 ||
        f[0] != 2 || f[1] != 1 || f[0x24/4] || f[0x28/4] ||
        !f[0x18/4] || f[0x18/4] > w || !f[0x1c/4] || f[0x1c/4] > h ||
        !f[0x10/4] || !f[0x14/4] || f[0x20/4] > 7 ||
        capture_nv16_coordinate(f, ow-1, false) >= f[0x18/4] ||
        capture_nv16_coordinate(f, oh-1, true) >= f[0x1c/4]) { return false; }
    for (unsigned k = 0; k < 2; k++) {
        if (s->z8_jdec_output_valid[k] && s->z8_jdec_format[k] == 1 &&
            p[0] == s->z8_jdec_y[k] && p[1] == s->z8_jdec_uv[k] &&
            w == s->z8_jdec_width[k] && h == s->z8_jdec_height[k] &&
            ip == s->z8_jdec_yp[k] && ip == s->z8_jdec_cp[k]) { owner = k; }
    }
    if (owner < 0) { return false; }
    for (unsigned k = 0; k < 4; k++) {
        if (!z8_playback_span(s, p[k], n[k])) { return false; }
        for (unsigned j = 0; j < k; j++) {
            if (p[k] < p[j]+n[j] && p[j] < p[k]+n[k]) { return false; }
        }
    }
    memcpy(s->z8_playback_input, a, sizeof(s->z8_playback_input));
    memcpy(s->z8_playback_output, b, sizeof(s->z8_playback_output));
    memcpy(s->z8_playback_geometry, f, sizeof(s->z8_playback_geometry));
    s->z8_playback_decode_core = owner;
    s->z8_playback_decode_epoch = s->z8_jdec_output_epoch[owner];
    s->z8_playback_outputs_armed = 0;
    s->z8_playback_requested = true;
    s->z8_playback_requests++;
    return true;
}

static void z8_playback_run(NikonZ8State *s)
{
    const uint32_t *a = s->z8_playback_input, *b = s->z8_playback_output;
    const uint32_t *f = s->z8_playback_geometry;
    unsigned ip = a[0x38/4], ih = a[0x50/4], op = b[0x38/4];
    unsigned ow = f[0x2c/4], oh = f[0x30/4];
    uint64_t y = capture_nv16_address(a, 0x20), uv = capture_nv16_address(a, 0x28);
    uint64_t oy = capture_nv16_address(b, 0x20), ouv = capture_nv16_address(b, 0x28);
    if (!s->z8_playback_requested || s->z8_playback_outputs_armed != 2) { return; }
    size_t ni = (size_t)ip*ih, no = (size_t)ow*oh;
    uint8_t *in = g_malloc(ni*2), *out = g_malloc(no*2);
    bool ok = address_space_read(&address_space_memory, y, MEMTXATTRS_UNSPECIFIED, in, ni) == MEMTX_OK &&
        address_space_read(&address_space_memory, uv, MEMTXATTRS_UNSPECIFIED, in+ni, ni) == MEMTX_OK;
    for (unsigned r = 0; ok && r < oh; r++) {
        unsigned sy = capture_nv16_coordinate(f, r, true);
        for (unsigned x = 0; x < ow; x++) {
            out[(size_t)r*ow+x] = in[(size_t)sy*ip+capture_nv16_coordinate(f, x, false)];
        }
        for (unsigned x = 0; x < ow; x += 2) {
            unsigned sx = capture_nv16_coordinate(f, x, false) & ~1u;
            out[no+(size_t)r*ow+x] = in[ni+(size_t)sy*ip+sx];
            out[no+(size_t)r*ow+x+1] = in[ni+(size_t)sy*ip+sx+1];
        }
    }
    for (unsigned r = 0; ok && r < oh; r++) {
        ok = address_space_write(&address_space_memory, oy+(uint64_t)r*op,
                MEMTXATTRS_UNSPECIFIED, out+(size_t)r*ow, ow) == MEMTX_OK &&
             address_space_write(&address_space_memory, ouv+(uint64_t)r*op,
                MEMTXATTRS_UNSPECIFIED, out+no+(size_t)r*ow, ow) == MEMTX_OK;
    }
    g_free(in); g_free(out);
    s->z8_playback_requested = false;
    if (!ok) { unknown_access(s, 0x15421104, 0x5001, 4, true); return; }
    s->z8_playback_jobs++; s->z8_playback_bytes += no*2;
    /* The finite A1 worker subscribes to input boundary bit4. The paired
     * first/last input events follow both complete RAM writes. Playback
     * does not start C1, so it receives no C1 capture completion. */
    s->engine1542_pending[1] |= 0x11;
    raw_pipeline_irq_update(s);
    fprintf(stderr, "Z8_PLAYBACK_RESIZE job=%" PRIu64 " %ux%u -> %ux%u bytes=%zu\n",
        s->z8_playback_jobs, a[0x4c/4], ih, ow, oh, no*2);
}

static bool z8_playback_output_control(NikonZ8State *s, unsigned i,
                                        hwaddr addr, uint64_t value)
{
    /* B6 has no RAM destination in this route. Its explicit strobe releases
     * the selected finite input; the configured B4 plane receives pixels. */
    const uint32_t *c = s->engine1542_config[i];
    const uint32_t *f = s->engine1542_config[21];
    const uint32_t *a = s->z8_playback_input;
    unsigned core = s->z8_playback_decode_core;
    bool valid = value == 1 && i == 9 && core < 2 &&
        s->z8_jdec_output_valid[core] &&
        s->z8_playback_decode_epoch == s->z8_jdec_output_epoch[core] &&
        c[0xc/4] == 0x41430010 &&
        c[0x10/4] == 1 && c[0x40/4] == 0x22 &&
        c[0x38/4] == a[0x38/4] && c[0x3c/4] == a[0x3c/4] &&
        !capture_nv16_address(c, 0x20) && !capture_nv16_address(c, 0x28) &&
        f[0] == 2 && f[1] == 1 && !f[2] && !f[3] &&
        f[0x10/4] == 16384 && f[0x14/4] == 16384 && !f[0x20/4] &&
        f[0x18/4] == a[0x4c/4] && f[0x1c/4] == a[0x50/4] &&
        f[0x2c/4] == a[0x4c/4] && f[0x30/4] == a[0x50/4];
    if (!valid) { unknown_access(s, addr, value, 4, true); return true; }
    s->engine1542_config[i][1] = value;
    s->z8_playback_outputs_armed = 2;
    fprintf(stderr, "Z8_PLAYBACK_OUTPUT base=%x armed=%u\n", engine1542_bases[i],
        s->z8_playback_outputs_armed);
    z8_playback_run(s);
    return true;
}

static bool z8_playback_control(NikonZ8State *s, hwaddr addr, uint64_t value)
{
    if (value == 0x5001) {
        if (!z8_playback_prepare(s)) { unknown_access(s, addr, value, 4, true); return true; }
        s->engine1542_config[1][1] = value;
        z8_playback_run(s);
    } else {
        if ((s->engine1542_config[1][1] & ~3u) != 0x5000) {
            unknown_access(s, addr, value, 4, true); return true;
        }
        s->z8_playback_requested = false;
        s->engine1542_config[1][1] = value;
    }
    return true;
}

static char *z8_playback_state(Object *obj, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    return g_strdup_printf("{\"requests\":%" PRIu64 ",\"jobs\":%" PRIu64 ",\"bytes\":%" PRIu64
        ",\"pending\":%s,\"physical_filter_verified\":false}",
        s->z8_playback_requests, s->z8_playback_jobs, s->z8_playback_bytes,
        s->z8_playback_requested ? "true" : "false");
}
