/* Copyright (C) 2026 RdWing: Z8 adaptation. */
/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Host-only controls for device-DMA provenance, with synthetic addresses. */
#include <assert.h>
#include <stdio.h>
#include "../qemu/nikon-z8-liveview-buffers.h"

int main(void)
{
    Z8LVBuffers store = { 0 };
    const uint64_t y = 0xa32547600ULL, uv = 0xa32741a00ULL;
    Z8LVBuffer *b;

    assert(!z8_lv_source(&store, y, uv, 640, 424, 640, true));
    assert(z8_lv_publish(&store, y, uv, 640, 424, 640, true, 1));
    b = z8_lv_source(&store, y, uv, 640, 424, 640, true);
    assert(b && b->generation == 1);
    /* A later write into a different ring buffer does not lose this one. */
    assert(z8_lv_publish(&store, y + 0x600000, uv + 0x600000,
                          640, 424, 640, true, 2));
    assert(z8_lv_source(&store, y, uv, 640, 424, 640, true) == b);
    assert(!z8_lv_source(&store, y, uv + 16, 640, 424, 640, true));
    assert(!z8_lv_source(&store, y, uv, 640, 424, 640, false));
    assert(!z8_lv_source(&store, y, uv, 640, 422, 640, true));
    b->consumed = b->generation;
    assert(!z8_lv_source(&store, y, uv, 640, 424, 640, true));
    assert(z8_lv_publish(&store, y, uv, 640, 424, 640, true, 3));
    assert(z8_lv_source(&store, y, uv, 640, 424, 640, true)->generation == 3);
    /* NV12 chroma has half as many rows. Beyond its end is unrelated RAM. */
    z8_lv_invalidate(&store, uv + 640 * 212, 1);
    assert(z8_lv_source(&store, y, uv, 640, 424, 640, true));
    z8_lv_invalidate(&store, uv + 640 * 212 - 1, 1);
    assert(!z8_lv_source(&store, y, uv, 640, 424, 640, true));
    assert(z8_lv_publish(&store, y, uv, 640, 424, 640, true, 4));
    /* A partial/failed future DMA invalidates before its attempted write. */
    z8_lv_invalidate(&store, y + 1, 1);
    assert(!z8_lv_source(&store, y, uv, 640, 424, 640, true));
    assert(!z8_lv_publish(&store, y, y + 16, 640, 424, 640, true, 5));
    assert(!z8_lv_publish(&store, y, uv, 640, 423, 640, true, 5));
    assert(!z8_lv_publish(&store, y, uv, 640, 424, 638, true, 5));
    assert(!z8_lv_publish(&store, UINT64_MAX - 1, uv,
                          640, 424, 640, true, 5));
    assert(!z8_lv_publish(&store, y, uv, 640, 424, 640, true, 0));
    assert(z8_lv_overlap(UINT64_MAX - 3, 4, UINT64_MAX, 1));
    assert(!z8_lv_overlap(UINT64_MAX - 3, 3, UINT64_MAX, 1));
    /* Capacity is fixed; evicting provenance may reject, never invent, data. */
    memset(&store, 0, sizeof(store));
    for (unsigned i = 0; i < Z8_LV_BUFFER_SLOTS + 1; i++) {
        assert(z8_lv_publish(&store, y + (uint64_t)i * 0x600000,
                              uv + (uint64_t)i * 0x600000,
                              640, 424, 640, true, i + 1));
    }
    assert(!z8_lv_source(&store, y, uv, 640, 424, 640, true));
    assert(z8_lv_source(&store, y + 32 * 0x600000ULL,
                         uv + 32 * 0x600000ULL, 640, 424, 640, true));
    puts("liveview buffer provenance controls passed; no guest or camera used");
    return 0;
}
