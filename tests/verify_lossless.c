/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright (C) 2026 RdWing */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../qemu/nikon-z8-lossless.h"

/* Explicit decoder codes, independent of the encoder's canonical builder.
 * Categories 0..14; MSB-first, with no JPEG byte stuffing. */
static const unsigned decode_codes[15] =
    {62, 126, 61, 28, 12, 4, 2, 0, 3, 5, 13, 29, 60, 254, 255};
static const unsigned decode_lengths[15] =
    {6, 7, 6, 5, 4, 3, 3, 2, 3, 3, 4, 5, 6, 8, 8};

static unsigned read_bits(const uint8_t *data, size_t size, size_t *bit, unsigned n)
{
    unsigned value = 0;
    assert(*bit + n <= size * 8);
    while (n--) {
        value = (value << 1) | ((data[*bit / 8] >> (7 - *bit % 8)) & 1);
        (*bit)++;
    }
    return value;
}

static void check_image(const uint16_t *pixels, unsigned width, unsigned height,
                        const uint16_t seeds[4])
{
    uint8_t input[4096], copy[4096], output[8192];
    unsigned stride = width * 7 / 4 + 13;
    size_t input_size = (size_t)stride * height, written = 0;
    assert(input_size <= sizeof(input));
    memset(input, 0xa5, sizeof(input));
    for (unsigned y = 0; y < height; y++) {
        for (unsigned x = 0; x < width; x += 4) {
            uint64_t word = 0;
            for (unsigned i = 0; i < 4; i++) {
                word |= (uint64_t)pixels[y * width + x + i] << (14 * i);
            }
            for (unsigned i = 0; i < 7; i++) {
                input[y * stride + x * 7 / 4 + i] = word >> (8 * i);
            }
        }
    }
    memcpy(copy, input, sizeof(input));
    memset(output, 0xac, sizeof(output));
    assert(nikon_z8_lossless14_encode(input, input_size, width, height, stride,
        seeds, output + 8, sizeof(output) - 16, &written));
    assert(!memcmp(input, copy, sizeof(input)));
    for (unsigned i = 0; i < 8; i++) {
        assert(output[i] == 0xac && output[sizeof(output) - 1 - i] == 0xac);
    }
    int vertical[2][2] = {{seeds[0], seeds[1]}, {seeds[2], seeds[3]}};
    size_t bit = 0;
    for (unsigned y = 0; y < height; y++) {
        int horizontal[2] = {0};
        for (unsigned x = 0; x < width; x++) {
            unsigned code = 0, category = 15;
            for (unsigned n = 1; n <= 8 && category == 15; n++) {
                code = (code << 1) | read_bits(output + 8, written, &bit, 1);
                for (unsigned c = 0; c < 15; c++) {
                    if (decode_lengths[c] == n && decode_codes[c] == code) {
                        category = c;
                        break;
                    }
                }
            }
            assert(category < 15);
            int difference = read_bits(output + 8, written, &bit, category);
            if (category && difference < (1 << (category - 1))) {
                difference -= (1 << category) - 1;
            }
            int sample = (x < 2 ? vertical[y & 1][x] : horizontal[x & 1]) + difference;
            if (x < 2) {
                vertical[y & 1][x] = sample;
            }
            horizontal[x & 1] = sample;
            assert(sample == pixels[y * width + x]);
        }
    }
    size_t failed = 99;
    assert(!nikon_z8_lossless14_encode(input, input_size - 1, width, height,
        stride, seeds, output, sizeof(output), &failed) && failed == 0);
    memset(output, 0xac, sizeof(output));
    assert(!nikon_z8_lossless14_encode(input, input_size, width, height,
        stride, seeds, output + 8, written - 1, &failed) && failed == 0);
    assert(output[7] == 0xac && output[8 + written - 1] == 0xac);
}

int main(void)
{
    const uint16_t seeds[4] = {2048, 2048, 2048, 2048};
    uint16_t pixels[1024];
    for (unsigned category = 0; category < 15; category++) {
        unsigned magnitude = (1U << category) - 1;
        for (unsigned y = 0; y < 2; y++) {
            pixels[4*y] = 0; pixels[4*y+1] = 16383;
            pixels[4*y+2] = magnitude; pixels[4*y+3] = 16383 - magnitude;
        }
        check_image(pixels, 4, 2, seeds);
    }
    uint32_t random = 1;
    for (unsigned i = 0; i < 1024; i++) {
        random = random * 1664525U + 1013904223U;
        pixels[i] = random >> 18;
    }
    const uint16_t uneven[4] = {0, 16383, 1024, 12288};
    check_image(pixels, 128, 8, uneven);

    /* Eight zero differences are exactly eight 111110 code words. */
    const uint8_t flat[14] = {0,8,0,2,128,0,32, 0,8,0,2,128,0,32};
    const uint8_t golden[10] = {0xfb,0xef,0xbe,0xfb,0xef,0xbe,0,0,0,0};
    uint8_t out[64]; size_t length = 0;
    assert(nikon_z8_lossless14_encode(flat, sizeof(flat), 4, 2, 7,
        seeds, out, sizeof(out), &length));
    assert(length == sizeof(golden) && !memcmp(out, golden, length));
    assert(!nikon_z8_lossless14_encode(flat, sizeof(flat), 4, 2, 0,
        seeds, out, sizeof(out), &length));
    assert(!nikon_z8_lossless14_encode(flat, sizeof(flat), 3, 2, 7,
        seeds, out, sizeof(out), &length));
    const uint16_t invalid[4] = {0, 0, 0, 16384};
    assert(!nikon_z8_lossless14_encode(flat, sizeof(flat), 4, 2, 7,
        invalid, out, sizeof(out), &length));
    puts("PASS lossless14: golden stream, all signed categories, Bayer predictors, row padding, input preservation and capacity rejection");
    return 0;
}
