/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright (C) 2026 RdWing */
/* Nikon 14-bit lossless output for the observed Z8 C3.11 F0 profile.
 * This encodes a guest-produced packed Bayer buffer. It does not implement
 * the physical codec, its timing, lossy modes, HE or HE*.
 * Format reference: LibRaw's nikon_load_raw in src/decoders/decoders_dcraw.cpp
 * (https://github.com/LibRaw/LibRaw). The canonical code lengths and category
 * ordering below describe the 14-bit lossless bitstream format.
 */
#ifndef NIKON_Z8_LOSSLESS_H
#define NIKON_Z8_LOSSLESS_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

typedef struct NikonZ8LosslessBits {
    uint8_t *out;
    size_t capacity, used;
    uint32_t pending;
    unsigned held;
} NikonZ8LosslessBits;

static bool nikon_z8_lossless_put(NikonZ8LosslessBits *b,
                                unsigned value, unsigned bits)
{
    b->pending = (b->pending << bits) | value;
    b->held += bits;
    while (b->held >= 8) {
        if (b->used == b->capacity) {
            return false;
        }
        b->held -= 8;
        b->out[b->used++] = b->pending >> b->held;
    }
    b->pending &= (1U << b->held) - 1;
    return true;
}

/* Input rows contain four little-endian 14-bit samples per seven bytes.
 * Row padding is ignored. Output is a continuous MSB-first Huffman stream.
 * The four predictors must match the NEF's F0 linearization metadata.
 * A failure leaves *written=0; callers must not DMA partial output or raise
 * completion. Input/output buffers must not overlap.
 */
static bool nikon_z8_lossless14_encode(const uint8_t *input, size_t input_size,
    unsigned width, unsigned height, unsigned stride, const uint16_t seeds[4],
    uint8_t *output, size_t capacity, size_t *written)
{
    static const unsigned counts[16] = {0, 1, 4, 2, 2, 3, 1, 2};
    static const unsigned categories[15] =
        {7, 6, 8, 5, 9, 4, 10, 3, 11, 12, 2, 0, 1, 13, 14};
    unsigned codes[15] = {0}, lengths[15] = {0};
    unsigned code = 0, index = 0;
    int vertical[2][2];
    NikonZ8LosslessBits b = {.out = output, .capacity = capacity};

    if (!written) {
        return false;
    }
    *written = 0;
    if (!input || !output || !seeds || !width || !height || (width & 3) ||
        width > 16384 || height > 16384 || stride < width * 7 / 4 ||
        height > input_size / stride) {
        return false;
    }
    for (unsigned i = 0; i < 4; i++) {
        if (seeds[i] > 16383) {
            return false;
        }
        vertical[i / 2][i % 2] = seeds[i];
    }
    for (unsigned n = 1; n <= 16; n++) {
        for (unsigned j = 0; j < counts[n - 1]; j++) {
            unsigned category = categories[index++];
            codes[category] = code++;
            lengths[category] = n;
        }
        code <<= 1;
    }
    for (unsigned y = 0; y < height; y++) {
        const uint8_t *row = input + (size_t)y * stride;
        int horizontal[2] = {0};
        for (unsigned x = 0; x < width; x += 4) {
            uint64_t packed = 0;
            for (unsigned i = 0; i < 7; i++) {
                packed |= (uint64_t)row[x * 7 / 4 + i] << (8 * i);
            }
            for (unsigned j = 0; j < 4; j++) {
                unsigned col = x + j;
                int sample = (packed >> (14 * j)) & 16383;
                int previous = col < 2 ? vertical[y & 1][col] : horizontal[col & 1];
                int difference = sample - previous;
                unsigned magnitude = difference < 0 ? -difference : difference;
                unsigned bits = 0;
                if (col < 2) {
                    vertical[y & 1][col] = sample;
                }
                horizontal[col & 1] = sample;
                for (unsigned n = magnitude; n; n >>= 1) {
                    bits++;
                }
                if (!nikon_z8_lossless_put(&b, codes[bits], lengths[bits])) {
                    return false;
                }
                /* Negative differences use the complement representation
                 * of their magnitude in the selected category's bit width. */
                unsigned payload = difference < 0 ?
                    (unsigned)(difference - 1) & ((1U << bits) - 1) : (unsigned)difference;
                if (bits && !nikon_z8_lossless_put(&b, payload, bits)) {
                    return false;
                }
            }
        }
    }
    if (b.held && !nikon_z8_lossless_put(&b, 0, 8 - b.held)) {
        return false;
    }
    /* Bounded reader lookahead after the final sample, outside image data. */
    for (unsigned i = 0; i < 4; i++) {
        if (!nikon_z8_lossless_put(&b, 0, 8)) {
            return false;
        }
    }
    /* LibRaw recognizes uncompressed Nikon data by its exact padded size.
     * Avoid that ambiguous size even when a compressed stream lands on it. */
    size_t packed_size = (size_t)((width * 7 / 4 + 15) & ~15U) * height;
    if (b.used == packed_size && !nikon_z8_lossless_put(&b, 0, 8)) {
        return false;
    }
    *written = b.used;
    return true;
}
#endif
