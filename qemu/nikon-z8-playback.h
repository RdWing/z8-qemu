/* Copyright (C) 2026 RdWing: Z8 adaptation. */
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
        (s->engine1542_pending[1] & 0x10011) || (s->engine1542_pending[7] & 0x1000) || (s->engine1542_pending[14]&0x11) || (s->engine1542_pending[11] & 0x20) ||
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
    size_t input_bytes = (size_t)ip*h;
    uint8_t *pixels = g_malloc(input_bytes*2);
    bool received = address_space_read(&address_space_memory,p[0],MEMTXATTRS_UNSPECIFIED,pixels,input_bytes)==MEMTX_OK &&
        address_space_read(&address_space_memory,p[1],MEMTXATTRS_UNSPECIFIED,pixels+input_bytes,input_bytes)==MEMTX_OK;
    if (!received) { g_free(pixels);return false; }
    g_free(s->z8_playback_pixels);s->z8_playback_pixels=pixels;
    s->z8_playback_active=true;
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
    uint64_t oy = capture_nv16_address(b, 0x20), ouv = capture_nv16_address(b, 0x28);
    if (!s->z8_playback_requested || s->z8_playback_outputs_armed != 2 || !s->z8_playback_pixels) { return; }
    unsigned core=s->z8_playback_decode_core;
    if (core>=2 || !s->z8_jdec_output_valid[core] ||
        s->z8_playback_decode_epoch!=s->z8_jdec_output_epoch[core]) {
        s->z8_playback_requested=false;s->z8_playback_active=false;
        g_free(s->z8_playback_pixels);s->z8_playback_pixels=NULL;
        unknown_access(s,0x15421104,0x5001,4,true);return;
    }
    size_t ni = (size_t)ip*ih, no = (size_t)ow*oh;
    const uint8_t *in = s->z8_playback_pixels;
    uint8_t *out = g_malloc(no*2);
    bool ok = true;
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
    g_free(s->z8_playback_pixels);s->z8_playback_pixels=NULL;g_free(out);
    s->z8_playback_requested = false;
    if (!ok) { unknown_access(s, 0x15421104, 0x5001, 4, true); return; }
    s->z8_playback_jobs++; s->z8_playback_bytes += no*2;
    /* This finite transfer has read its complete input and written both
     * output planes. Input first/data/end and B4 writer causes follow that
     * work, never a configuration strobe. STOP can separately acknowledge
     * the now-quiescent finite input after its native wait is cleared. */
    s->engine1542_pending[1] |= 0x10011;
    s->engine1542_pending[7] |= 0x1000;
    raw_pipeline_irq_update(s);
    fprintf(stderr, "Z8_PLAYBACK_RESIZE job=%" PRIu64 " %ux%u -> %ux%u bytes=%zu\n",
        s->z8_playback_jobs, a[0x4c/4], ih, ow, oh, no*2);
}

static bool z8_playback_output_control(NikonZ8State *s, unsigned i,
                                        hwaddr addr, uint64_t value)
{
    /* B6 has no RAM destination. Original 40cb8738 pulses it only after
     * an input timeout, through 40c2606c / 40c26084. Retain this control;
     * it is not permission to perform a delayed pixel transfer. */
    const uint32_t *c = s->engine1542_config[i];
    const uint32_t *f = s->engine1542_config[21];
    const uint32_t *a = s->z8_playback_input;
    bool valid = value == 1 && i == 9 &&
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
    fprintf(stderr, "Z8_PLAYBACK_CONTROL base=%x pulse=1; no DMA or completion\n", engine1542_bases[i]);
    return true;
}

/* Z8's finite A1 route selects E source14 before arming B6. Supply its
 * requested functional luma bins from the accepted NV16 input, not from a
 * stale live-view surface. E cause1 follows those actual pixel reads. */
static void z8_playback_histogram(NikonZ8State *s)
{
    const uint32_t *e=s->engine1542_config[14],*a=s->z8_playback_input;
    unsigned core=s->z8_playback_decode_core;
    if (core>=2 || !s->z8_jdec_output_valid[core] ||
        s->z8_playback_decode_epoch!=s->z8_jdec_output_epoch[core]) { return; }
    if (!s->raw_pipeline_output_done || !s->z8_e_armed || !s->z8_playback_pixels ||
        !(e[0]&1) || ((e[1]>>4)&15)!=14 || !(e[2]&1) || !(e[0x50/4]&1) ||
        (s->engine1542_pending[14]&0x11)) { return; }
    unsigned w=a[0x4c/4],h=a[0x50/4],pitch=a[0x38/4];
    memset(s->raw_histogram,0,sizeof(s->raw_histogram));
    for (unsigned y=0;y<h;y++) {
        for (unsigned x=0;x<w;x++) {
            uint32_t *bin=&s->raw_histogram[0][s->z8_playback_pixels[(size_t)y*pitch+x]];
            if (*bin<0xffffff) { (*bin)++; }
        }
    }
    s->raw_histogram_source=14;s->raw_histogram_luma=true;
    s->raw_histogram_samples=(uint64_t)w*h;s->raw_histogram_frames++;
    /* The native finite initializer waits on E cause0. The observed E
     * client mask is zero; do not invent a separate client end event. */
    s->z8_e_armed=false;s->engine1542_pending[14]|=1;
}

static bool z8_playback_control(NikonZ8State *s, hwaddr addr, uint64_t value)
{
    if (value == 0x5001) {
        if (!z8_playback_prepare(s)) { unknown_access(s, addr, value, 4, true); return true; }
        s->engine1542_config[1][1] = value;
        /* A1 START owns the finite transfer. The native initializer
         * waits for input and E data before any timeout-only B6 pulse. */
        s->z8_playback_outputs_armed=2;
        z8_playback_histogram(s);
        z8_playback_run(s);
    } else {
        if ((s->engine1542_config[1][1] & ~3u) != 0x5000) {
            unknown_access(s, addr, value, 4, true); return true;
        }
        bool active=s->z8_playback_active;
        s->z8_playback_requested=false;s->z8_playback_active=false;
        g_free(s->z8_playback_pixels);s->z8_playback_pixels=NULL;
        s->engine1542_config[1][1] = value;
        /* Original 40cb87ec clears internal flag0x10 before STOP. All
         * input DMA is already quiescent; publish its finite end now.
         * A cancelled request creates no output-completion notification. */
        if (active) { s->engine1542_pending[1] |= 0x10000;raw_pipeline_irq_update(s); }
    }
    return true;
}

static char *z8_playback_state(Object *obj, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    return g_strdup_printf("{\"requests\":%" PRIu64 ",\"jobs\":%" PRIu64 ",\"bytes\":%" PRIu64
        ",\"pending\":%s,\"input_active\":%s,\"owned_input\":%s,\"physical_filter_verified\":false}",
        s->z8_playback_requests, s->z8_playback_jobs, s->z8_playback_bytes,
        s->z8_playback_requested ? "true" : "false",
        s->z8_playback_active ? "true" : "false",s->z8_playback_pixels ? "true" : "false");
}
