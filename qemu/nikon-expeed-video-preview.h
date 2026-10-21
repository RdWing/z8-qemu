/* Copyright (C) 2026 RdWing: Z8 adaptation. */
/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Finite A1 byte8/packed10 NV12 RAM -> B3/B4/B5 preview outputs.
 * Functional nearest sampling/10-to-8 conversion, NOT Nikon ISP algorithms.
 * Native578 submits this independent RAM job during movie stop. No header,
 * codec, OS or camera-file completion is supplied by this device. */
#define WL_PREVIEW_BITS_A ((1u<<1)|(1u<<2)|(1u<<3)|(1u<<4)| \
    (1u<<8)|(1u<<9)|(1u<<10)|(1u<<11)|(1u<<14)|(1u<<15)| \
    (1u<<16)|(1u<<19)|(1u<<20))
#define WL_PREVIEW_BITS_B ((1u<<3)|(1u<<4)|(1u<<8)|(1u<<9)| \
    (1u<<10)|(1u<<11)|(1u<<14)|(1u<<15)|(1u<<16))
#define WL_PREVIEW_BITS_F 0x1fffU

static void video_preview_written(NikonZ8State *s, unsigned i, unsigned off)
{
    int slot = i == 1 ? 0 : i >= 6 && i <= 8 ? i - 5 :
        i >= 18 && i <= 20 ? i - 14 : -1;
    if (s->video_preview_model && slot >= 0 && off < 0x80) {
        s->video_preview_written[slot] |= 1u << (off / 4);
    }
}

static uint8_t video_preview_sample(const uint8_t *p, unsigned pitch,
                                    unsigned x, unsigned y, unsigned bits)
{
    if (bits == 8) { return p[(size_t)y*pitch+(x^3u)]; }
    uint32_t word = ldl_be_p(p + (size_t)y * pitch + (x / 3) * 4);
    unsigned sample = (word >> (22 - (x % 3) * 10)) & 1023;
    return (sample * 255 + 511) / 1023;
}

static bool video_preview_transfer(NikonZ8State *s)
{
    const uint32_t *a = s->engine1542_config[1];
    unsigned w = a[0x4c/4], h = a[0x50/4], pitch = a[0x38/4];
    uint64_t p[8], n[8], total = 0;
    uint8_t *input = NULL, *output[3] = {NULL};
    bool ok = false;
    unsigned bits = a[3] == 0x31000000 ? 8 : 10;
    unsigned minrow = bits == 8 ? ((w+3)&~3u) : (w+2)/3*4;
    if ((s->video_preview_written[0] & WL_PREVIEW_BITS_A) != WL_PREVIEW_BITS_A ||
        (a[1] != 0x3802 && a[1] != 0x3800) || a[2] != 0x78000000 ||
        (a[3] != 0x31000200 && a[3] != 0x31000000) || a[4] != 1 || a[0x40/4] != 0x0f000022 ||
        !w || (w & 1) || w > 8192 || !h || (h & 1) || h > 8192 ||
        pitch < minrow || pitch > 32768 || (pitch & 3) ||
        a[0x3c/4] != pitch || s->engine1542_pending[1] ||
        s->engine1543_active[0] || s->engine1543_active[1] ||
        s->capture_nv16_requested) { return false; }
    p[0] = capture_nv16_address(a, 0x20);
    p[1] = capture_nv16_address(a, 0x28);
    n[0] = (uint64_t)pitch * h; n[1] = n[0] / 2;
    for (unsigned j = 0; j < 3; j++) {
        const uint32_t *b = s->engine1542_config[6+j];
        const uint32_t *f = s->engine1542_config[18+j];
        unsigned ow = f[0x2c/4], oh = f[0x30/4], op = b[0x38/4];
        if ((s->video_preview_written[1+j] & WL_PREVIEW_BITS_B) != WL_PREVIEW_BITS_B ||
            (s->video_preview_written[4+j] & WL_PREVIEW_BITS_F) != WL_PREVIEW_BITS_F ||
            b[0xc/4] != 0x41000010 || b[0x10/4] != 1 || b[0x40/4] != 0x22 ||
            b[0x3c/4] != op || (f[0] != 0 && f[0] != 2 && f[0] != 4) ||
            (f[1] != 1 && f[1] != 4) || f[0x18/4] != w || f[0x1c/4] != h ||
            f[0x24/4] || f[0x28/4] || !ow || (ow & 1) || ow > 8192 ||
            !oh || (oh & 1) || oh > 8192 || op < ow || op > 32768 ||
            !f[0x10/4] || !f[0x14/4] || f[0x20/4] > 7 ||
            capture_nv16_coordinate(f, ow-1, false) >= w ||
            capture_nv16_coordinate(f, oh-1, true) >= h) { return false; }
        p[2+j*2] = capture_nv16_address(b, 0x20);
        p[3+j*2] = capture_nv16_address(b, 0x28);
        n[2+j*2] = (uint64_t)op * oh;
        n[3+j*2] = n[2+j*2] / (f[0] == 0 ? 2 : 1);
        total += n[2+j*2] + n[3+j*2];
    }
    if (total > 192 * MiB) { return false; }
    for (unsigned j = 0; j < 8; j++) {
        if (!capture_nv16_span(s, p[j], n[j])) { return false; }
        for (unsigned k = 0; k < j; k++) {
            if (p[j] < p[k]+n[k] && p[k] < p[j]+n[j]) { return false; }
        }
    }
    input = g_malloc(n[0]+n[1]);
    if (address_space_read(&address_space_memory, p[0], MEMTXATTRS_UNSPECIFIED,
            input, n[0]) != MEMTX_OK ||
        address_space_read(&address_space_memory, p[1], MEMTXATTRS_UNSPECIFIED,
            input+n[0], n[1]) != MEMTX_OK) { goto done; }
    for (unsigned j = 0; j < 3; j++) {
        const uint32_t *b = s->engine1542_config[6+j];
        const uint32_t *f = s->engine1542_config[18+j];
        unsigned ow = f[0x2c/4], oh = f[0x30/4], op = b[0x38/4];
        unsigned sub = f[0] == 0 ? 2 : 1;
        output[j] = g_malloc(n[2+j*2]+n[3+j*2]);
        memset(output[j], 0, n[2+j*2]);
        memset(output[j]+n[2+j*2], 128, n[3+j*2]);
        for (unsigned r = 0; r < oh; r++) {
            unsigned sy = capture_nv16_coordinate(f, r, true);
            for (unsigned x = 0; x < ow; x++) {
                unsigned sx = capture_nv16_coordinate(f, x, false);
                output[j][(size_t)r*op+x] = video_preview_sample(input,pitch,sx,sy,bits);
            }
        }
        for (unsigned r = 0; r < oh/sub; r++) {
            unsigned sy = capture_nv16_coordinate(f, r*sub, true)/2;
            for (unsigned x = 0; x < ow; x += 2) {
                unsigned sx = capture_nv16_coordinate(f, x, false) & ~1u;
                for (unsigned c = 0; c < 2; c++) {
                    output[j][n[2+j*2]+(size_t)r*op+x+c] =
                        video_preview_sample(input+n[0],pitch,sx+c,sy,bits);
                }
            }
        }
    }
    /* Validate and construct every output before any destination write.
     * All addresses are RAM spans, never MMIO or guest control structures. */
    for (unsigned j = 0; j < 3; j++) {
        if (address_space_write(&address_space_memory,p[2+j*2],MEMTXATTRS_UNSPECIFIED,
                output[j],n[2+j*2]) != MEMTX_OK ||
            address_space_write(&address_space_memory,p[3+j*2],MEMTXATTRS_UNSPECIFIED,
                output[j]+n[2+j*2],n[3+j*2]) != MEMTX_OK) { goto done; }
    }
    for (unsigned j = 0; j < 3; j++) {
        const uint32_t *b = s->engine1542_config[6+j], *f = s->engine1542_config[18+j];
        s->video_preview_y[j] = p[2+j*2]; s->video_preview_uv[j] = p[3+j*2];
        s->video_preview_w[j] = f[0x2c/4]; s->video_preview_h[j] = f[0x30/4];
        s->video_preview_pitch[j] = b[0x38/4]; s->video_preview_sub[j] = f[0] == 0 ? 2 : 1;
    }
    s->video_preview_jobs++;
    s->video_preview_input_bytes += n[0]+n[1];
    s->video_preview_output_bytes += total;
    memset(s->video_preview_written,0,sizeof(s->video_preview_written));
    s->engine1542_config[1][1] = 0x3801;
    s->engine1542_pending[1] |= 0x11;
    raw_pipeline_irq_update(s);
    ok = true;
done:
    g_free(input);
    for (unsigned j = 0; j < 3; j++) { g_free(output[j]); }
    return ok;
}

static bool get_video_preview_model(Object *obj, Error **errp)
{ return NIKON_Z8_LAB(obj)->video_preview_model; }
static void set_video_preview_model(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    if (s->image_ram.ram || s->image_ram.rom_device) {
        error_setg(errp,"video preview RAM model immutable after realization");return;
    }
    s->video_preview_model = value;
}
static char *get_video_preview_state(Object *obj, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    return g_strdup_printf("{\"enabled\":%s,\"jobs\":%"PRIu64
        ",\"input_bytes\":%"PRIu64",\"output_bytes\":%"PRIu64
        ",\"pending\":%u,\"written\":[%u,%u,%u,%u,%u,%u,%u],"
        "\"original_algorithm\":false,\"file_accepted\":false}",
        s->video_preview_model?"true":"false",s->video_preview_jobs,
        s->video_preview_input_bytes,s->video_preview_output_bytes,s->engine1542_pending[1],
        s->video_preview_written[0],s->video_preview_written[1],s->video_preview_written[2],
        s->video_preview_written[3],s->video_preview_written[4],s->video_preview_written[5],
        s->video_preview_written[6]);
}
