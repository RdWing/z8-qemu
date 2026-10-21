/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Explicit functional D8 -> packed Y/UV RAM -> source1 RGB RAM route.
 * The packed12 layouts and BT.601 transform below are simulator contracts,
 * not measured Nikon formats/ISP arithmetic. Native configuration identifies
 * the paired RAM spans. Neither a firmware PC nor an application flag is used.
 * The existing functional Bayer tone path has eight-bit component precision;
 * twelve-bit storage does not make this original twelve-bit ISP processing.
 */

static void source_ram_pack12(uint8_t *p, unsigned index, unsigned value)
{
    unsigned off = index * 3 / 2;
    value = MIN(value, 4095);
    if (index & 1) {
        p[off] = (p[off] & 15) | (value << 4);
        p[off + 1] = value >> 4;
    } else {
        p[off] = value;
        p[off + 1] = (p[off + 1] & 0xf0) | (value >> 8);
    }
}

static unsigned source_ram_unpack12(const uint8_t *p, unsigned index)
{
    unsigned off = index * 3 / 2;
    return index & 1 ? (p[off] >> 4) | (p[off + 1] << 4) :
                      p[off] | ((p[off + 1] & 15) << 8);
}

static bool source_ram_overlap(uint64_t a, uint64_t an, uint64_t b, uint64_t bn)
{
    return a < b + bn && b < a + an;
}

static void video_source_ram_frame(NikonZ8State *s, const NikonRawPixels *pixels,
                                   uint64_t epoch)
{
    Z8Engine1518 *e = &s->engine1518[2];
    const uint32_t *d = s->engine150d8_config_latched, *c = e->config;
    if (!s->video_source_ram_model || !pixels || !epoch ||
        epoch <= s->video_source_ram_epoch || !s->event_timing_active ||
        !(s->engine150c_active & 0x2000) || (s->engine_150c_init[6] & 0x2000) ||
        !(d[0] & 1) || !d[0x118/4] || !c[0x30/4] ||
        s->engine151_active[1] || (e->pending & 0x28100000)) {
        return;
    }
    unsigned row = s->video_source_ram_row, off = (0x100 + row * 0x400) / 4;
    unsigned w = d[0x88/4], h = d[0x8c/4], pitch = d[0x108/4];
    unsigned ow = (c[0xa4/4] & 0x3fff) + 1;
    unsigned oh = ((c[0xa4/4] >> 16) & 0x3fff) + 1;
    unsigned opitch = c[0xb0/4];
    uint64_t bytes = (uint64_t)pitch * h, obytes = (uint64_t)opitch * oh;
    uint64_t y, uv, input_y, input_uv, rgb;
    uint64_t dy = d[(0x150 + row * 8)/4] | (uint64_t)d[(0x154 + row * 8)/4] << 32;
    uint64_t duv = d[(0x250 + row * 8)/4] | (uint64_t)d[(0x254 + row * 8)/4] << 32;
    uint64_t cy = c[off] | (uint64_t)(c[off+1] & 15) << 32;
    uint64_t cuv = c[off+2] | (uint64_t)(c[off+3] & 15) << 32;
    uint64_t crgb = c[off+4] | (uint64_t)(c[off+5] & 15) << 32;
    /* Admit a declared semiplanar-to-packed route only. Matched geometry is
     * deliberately required until the separate warp/crop contract is known. */
    if (!w || !h || ((w | h) & 1) || w > 2048 || h > 2048 ||
        w != (c[0x80/4] & 0x7fff) || h != (c[0x80/4] >> 16) ||
        ow != w || oh != h || pitch < w * 3 / 2 || pitch > 8192 ||
        pitch != c[0x88/4] || pitch != c[0x8c/4] ||
        opitch < w * 9 / 2 || opitch > 16384 || !bytes || bytes > 16*MiB ||
        !obytes || obytes > 32*MiB || c[0xbc/4] != 2 || c[0xc0/4] != 1 ||
        c[0xc4/4] != 0x22 || c[0xd4/4] != 2 || c[0x98/4] || c[0xa0/4] ||
        !raw_pipeline_address(s, dy, bytes, &y) ||
        !raw_pipeline_address(s, duv, bytes, &uv) ||
        !raw_pipeline_address(s, cy, bytes, &input_y) ||
        !raw_pipeline_address(s, cuv, bytes, &input_uv) ||
        !raw_pipeline_address(s, crgb, obytes, &rgb) ||
        y != input_y || uv != input_uv ||
        source_ram_overlap(y, bytes, uv, bytes) ||
        source_ram_overlap(y, bytes, rgb, obytes) ||
        source_ram_overlap(uv, bytes, rgb, obytes)) {
        s->video_source_ram_rejects++;
        return;
    }
    for (unsigned i = 0; i < 3; i++) {
        uint64_t n = (uint64_t)s->raw_pipeline_stride[i] * s->raw_pipeline_height[i];
        uint64_t un = n / (s->raw_pipeline_uv_half[i] ? 2 : 1);
        uint64_t ptrs[3] = {y, uv, rgb}, sizes[3] = {bytes, bytes, obytes};
        for (unsigned j = 0; j < 3; j++) {
            if (source_ram_overlap(ptrs[j], sizes[j], s->raw_pipeline_y[i], n) ||
                source_ram_overlap(ptrs[j], sizes[j], s->raw_pipeline_uv[i], un)) {
                s->video_source_ram_rejects++;
                return;
            }
        }
    }
    uint8_t *nv16 = nikon_raw_pixels_yuv(pixels, w, h, w, false);
    if (!nv16) {
        s->video_source_ram_rejects++;
        return;
    }
    uint8_t *yp = g_malloc0(bytes), *uvp = g_malloc0(bytes);
    uint8_t *out = g_malloc0(obytes);
    for (unsigned iy = 0; iy < h; iy++) {
        for (unsigned x = 0; x < w; x++) {
            source_ram_pack12(yp + (size_t)iy * pitch, x,
                             ((unsigned)nv16[(size_t)iy*w+x] * 4095 + 127) / 255);
            source_ram_pack12(uvp + (size_t)iy * pitch, x,
                             ((unsigned)nv16[(size_t)w*h+(size_t)iy*w+x] * 4095 + 127) / 255);
        }
    }
    g_free(nv16);
    /* The source processor reads actual RAM after the producer's full write.
     * It cannot substitute the host Bayer cache for its configured inputs. */
    bool ok = address_space_write(&address_space_memory, y, MEMTXATTRS_UNSPECIFIED, yp, bytes) == MEMTX_OK &&
        address_space_write(&address_space_memory, uv, MEMTXATTRS_UNSPECIFIED, uvp, bytes) == MEMTX_OK &&
        address_space_read(&address_space_memory, input_y, MEMTXATTRS_UNSPECIFIED, yp, bytes) == MEMTX_OK &&
        address_space_read(&address_space_memory, input_uv, MEMTXATTRS_UNSPECIFIED, uvp, bytes) == MEMTX_OK;
    if (ok) {
        for (unsigned iy = 0; iy < h; iy++) {
            for (unsigned x = 0; x < w; x++) {
                int yy = source_ram_unpack12(yp+(size_t)iy*pitch, x);
                int u = (int)source_ram_unpack12(uvp+(size_t)iy*pitch, x&~1u)-2048;
                int v = (int)source_ram_unpack12(uvp+(size_t)iy*pitch, x|1u)-2048;
                int values[3] = {yy+((359*v+128)>>8),
                    yy-((88*u+183*v+128)>>8), yy+((454*u+128)>>8)};
                for (unsigned k = 0; k < 3; k++) {
                    source_ram_pack12(out+(size_t)iy*opitch, x*3+k, CLAMP(values[k], 0, 4095));
                }
            }
        }
        ok = address_space_write(&address_space_memory, rgb, MEMTXATTRS_UNSPECIFIED, out, obytes) == MEMTX_OK;
    }
    g_free(yp); g_free(uvp); g_free(out);
    if (!ok) {
        s->video_source_ram_rejects++;
        return;
    }
    s->video_source_ram_epoch = epoch;
    s->video_source_ram_jobs++;
    s->video_source_ram_bytes += bytes*2 + obytes;
    s->video_source_ram_y = y; s->video_source_ram_uv = uv;
    s->video_source_ram_rgb = rgb;
    s->video_source_ram_width = w; s->video_source_ram_height = h;
    s->video_source_ram_pitch = pitch; s->video_source_ram_rgb_pitch = opitch;
    s->video_source_ram_row = (row+1) & 3;
    e->pending |= 0x08100000;
    e->stream_frames++;
    if (s->video_secondary_source_end_model && ++s->video_secondary_source_group == 3) {
        e->pending |= 0x20000000;
        s->video_secondary_source_ends++;
    }
    engine1518_update_irq(e);
}

static bool get_video_source_ram_model(Object *obj, Error **errp)
{ return NIKON_Z8_LAB(obj)->video_source_ram_model; }

static void set_video_source_ram_model(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    if (s->image_ram.ram || s->image_ram.rom_device) {
        error_setg(errp, "video-source-ram-model is immutable after realization");
        return;
    }
    s->video_source_ram_model = value;
}

static char *get_video_source_ram_state(Object *obj, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    return g_strdup_printf("{\"enabled\":%s,\"epoch\":%"PRIu64",\"jobs\":%"PRIu64
        ",\"bytes\":%"PRIu64",\"rejects\":%"PRIu64",\"row\":%u,\"y\":%"PRIu64
        ",\"uv\":%"PRIu64",\"rgb\":%"PRIu64",\"width\":%u,\"height\":%u,"
        "\"pitch\":%u,\"rgb_pitch\":%u,\"storage_bits\":12,\"component_precision_bits\":8,"
        "\"original_algorithm\":false,\"physical_format_verified\":false,"
        "\"scope\":\"functional D8 YUV12 RAM and matching source1 RGB12 RAM; own pending/W1C; no warp or original ISP arithmetic\"}",
        s->video_source_ram_model?"true":"false", s->video_source_ram_epoch,
        s->video_source_ram_jobs, s->video_source_ram_bytes, s->video_source_ram_rejects,
        s->video_source_ram_row, s->video_source_ram_y, s->video_source_ram_uv,
        s->video_source_ram_rgb, s->video_source_ram_width, s->video_source_ram_height,
        s->video_source_ram_pitch, s->video_source_ram_rgb_pitch);
}
