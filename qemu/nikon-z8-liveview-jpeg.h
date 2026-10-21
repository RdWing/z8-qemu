/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Functional mode32 contract: NV12 from a completed RAW-model generation.
 * C2.00's original descriptor value 2 selects mode32. The source model's
 * submitted half-chroma configuration supplies the functional NV12 layout;
 * this is not validation of the physical EXPEED codec or ISP. */
#ifndef HW_ARM_NIKON_Z8_LIVEVIEW_JPEG_H
#define HW_ARM_NIKON_Z8_LIVEVIEW_JPEG_H

#include "nikon-z8-jpeg-reset.h"

static bool engine15e2_liveview_reset_write(NikonZ8State *s, unsigned bank,
        unsigned off, uint64_t value, unsigned size)
{
    if (!s->z8_lv_jpeg || bank != s->engine15e2_jpeg_bank) {
        return false;
    }
    uint32_t *c = s->engine15e2_config[bank];
    Z8JPEGResetAction action = z8_jpeg_reset_action(c, off, value, size,
        s->engine15e2_jpeg_requested, s->engine15e2_jpeg_result_valid,
        s->engine15e2_jpeg_pending, s->engine15e2_jpeg_core);

    if (action == Z8_JPEG_RESET_DISARM) {
        c[off / 4] = 0;
        return true;
    }
    if (action != Z8_JPEG_RESET_CANCEL) {
        return false;
    }
    s->engine15e2_jpeg_requested = false;
    s->engine15e2_deferred_failed = false;
    c[1] = 0;
    s->engine15e2_idle_resets[bank]++;
    s->z8_lv_jpeg_cancels++;
    fprintf(stderr, "Z8_LIVEVIEW_JPEG_CANCEL bank=%u; no output or IRQ\n", bank);
    return true;
}

static Z8LVBuffer *engine15e2_liveview_source(NikonZ8State *s, unsigned bank)
{
    const uint32_t *c = s->engine15e2_config[bank];

    if (!s->z8_lv_jpeg || c[0] != 0x32 ||
        c[0x410 / 4] != c[0x414 / 4]) {
        return NULL;
    }
    return z8_lv_source(&s->z8_lv_buffers,
                         (uint64_t)c[0x430 / 4] << 4,
                         (uint64_t)c[0x434 / 4] << 4,
                         c[0x418 / 4], c[0x41c / 4], c[0x410 / 4], true);
}

static char *get_z8_liveview_jpeg_state(Object *obj, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    GString *out = g_string_new(NULL);
    unsigned n = 0;

    g_string_append_printf(out, "{\"enabled\":%s,\"jobs\":%" PRIu64
        ",\"last_generation\":%" PRIu64 ",\"cancels\":%" PRIu64 ",\"buffers\":[",
        s->z8_lv_jpeg ? "true" : "false", s->z8_lv_jpeg_jobs,
        s->z8_lv_jpeg_generation, s->z8_lv_jpeg_cancels);
    for (unsigned i = 0; i < Z8_LV_BUFFER_SLOTS; i++) {
        const Z8LVBuffer *b = &s->z8_lv_buffers.slots[i];

        if (!b->valid) {
            continue;
        }
        g_string_append_printf(out, "%s{\"y\":%" PRIu64
            ",\"uv\":%" PRIu64 ",\"generation\":%" PRIu64
            ",\"consumed\":%" PRIu64 ",\"width\":%u,\"height\":%u,"
            "\"stride\":%u,\"nv12\":%s}", n++ ? "," : "",
            b->y, b->uv, b->generation, b->consumed, b->width,
            b->height, b->stride, b->nv12 ? "true" : "false");
    }
    g_string_append(out, "],\"physical_algorithm_verified\":false,"
        "\"scope\":\"completed RAW-model NV12 RAM generations, baseline libjpeg;"
        " no native buffer-lifetime or RTSP acceptance claim\"}");
    return g_string_free(out, false);
}

#endif
