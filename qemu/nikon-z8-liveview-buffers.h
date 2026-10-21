/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Bounded provenance for RAM actually written by the functional RAW model.
 * This records completed device writes, not Nikon allocator ownership or
 * measured silicon timing. A generation can be encoded once; overwrites
 * invalidate older provenance before the next DMA is attempted. */
#ifndef HW_ARM_NIKON_Z8_LIVEVIEW_BUFFERS_H
#define HW_ARM_NIKON_Z8_LIVEVIEW_BUFFERS_H

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#define Z8_LV_BUFFER_SLOTS 32

typedef struct Z8LVBuffer {
    uint64_t y, uv, generation, consumed;
    unsigned width, height, stride;
    bool valid, nv12;
} Z8LVBuffer;

typedef struct Z8LVBuffers {
    Z8LVBuffer slots[Z8_LV_BUFFER_SLOTS];
} Z8LVBuffers;

static bool z8_lv_overlap(uint64_t a, uint64_t n, uint64_t b, uint64_t m)
{
    /* Subtraction avoids overflowing either exclusive end. */
    return n && m && (a <= b ? b - a < n : a - b < m);
}

static void z8_lv_invalidate(Z8LVBuffers *store, uint64_t address,
                              uint64_t bytes)
{
    for (unsigned i = 0; i < Z8_LV_BUFFER_SLOTS; i++) {
        Z8LVBuffer *b = &store->slots[i];
        uint64_t ybytes = (uint64_t)b->stride * b->height;
        uint64_t uvbytes = ybytes / (b->nv12 ? 2 : 1);

        if (b->valid && (z8_lv_overlap(address, bytes, b->y, ybytes) ||
                         z8_lv_overlap(address, bytes, b->uv, uvbytes))) {
            b->valid = false;
        }
    }
}

static bool z8_lv_publish(Z8LVBuffers *store, uint64_t y, uint64_t uv,
                           unsigned width, unsigned height, unsigned stride,
                           bool nv12, uint64_t generation)
{
    uint64_t ybytes = (uint64_t)stride * height;
    uint64_t uvbytes = ybytes / (nv12 ? 2 : 1);
    unsigned slot = 0;

    if (!generation || !width || !height || ((width | height | stride) & 1) ||
        stride < width || stride > 8192 || height > 4096 || width > 4096 ||
        y > UINT64_MAX - ybytes || uv > UINT64_MAX - uvbytes ||
        z8_lv_overlap(y, ybytes, uv, uvbytes)) {
        return false;
    }
    z8_lv_invalidate(store, y, ybytes);
    z8_lv_invalidate(store, uv, uvbytes);
    for (unsigned i = 0; i < Z8_LV_BUFFER_SLOTS; i++) {
        if (!store->slots[i].valid) {
            slot = i;
            break;
        }
        if (store->slots[i].generation < store->slots[slot].generation) {
            slot = i;
        }
    }
    store->slots[slot] = (Z8LVBuffer) {
        .y = y, .uv = uv, .generation = generation,
        .width = width, .height = height, .stride = stride,
        .valid = true, .nv12 = nv12,
    };
    return true;
}

static Z8LVBuffer *z8_lv_source(Z8LVBuffers *store, uint64_t y, uint64_t uv,
                                  unsigned width, unsigned height,
                                  unsigned stride, bool nv12)
{
    for (unsigned i = 0; i < Z8_LV_BUFFER_SLOTS; i++) {
        Z8LVBuffer *b = &store->slots[i];

        if (b->valid && b->generation != b->consumed &&
            b->y == y && b->uv == uv && b->width == width &&
            b->height == height && b->stride == stride && b->nv12 == nv12) {
            return b;
        }
    }
    return NULL;
}

#endif
