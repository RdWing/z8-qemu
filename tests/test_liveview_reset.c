/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <assert.h>
#include <stdio.h>
#include "../qemu/nikon-z8-jpeg-reset.h"

int main(void)
{
    uint32_t c[0x500 / 4] = { [0] = 0x32,
        [0x400 / 4] = 0x4000, [0x404 / 4] = 0x4000 };
#define STEP(off, value, size, requested, valid, pending, core) \
    z8_jpeg_reset_action(c, off, value, size, requested, valid, pending, core)
    assert(STEP(4, 0x80000001, 4, true, false, 0, 0) == Z8_JPEG_RESET_NONE);
    assert(STEP(0x400, 0, 4, true, false, 0, 0) == Z8_JPEG_RESET_DISARM);
    c[0x400 / 4] = 0;
    assert(STEP(4, 0x80000001, 4, true, false, 0, 0) == Z8_JPEG_RESET_NONE);
    assert(STEP(0x404, 0, 4, true, false, 0, 0) == Z8_JPEG_RESET_DISARM);
    c[0x404 / 4] = 0;
    assert(STEP(4, 0x80000001, 4, true, false, 0, 0) == Z8_JPEG_RESET_CANCEL);
    assert(STEP(4, 0x80000001, 4, true, false, 0x8000000, 0) == Z8_JPEG_RESET_NONE);
    assert(STEP(4, 0x80000001, 4, true, false, 0, 0x80000000) == Z8_JPEG_RESET_NONE);
    assert(STEP(4, 0x80000001, 4, true, true, 0, 0) == Z8_JPEG_RESET_NONE);
    assert(STEP(4, 0x80000001, 4, false, false, 0, 0) == Z8_JPEG_RESET_NONE);
    assert(STEP(4, 0x80000001, 8, true, false, 0, 0) == Z8_JPEG_RESET_NONE);
    assert(STEP(4, 0x180000001ULL, 4, true, false, 0, 0) == Z8_JPEG_RESET_NONE);
    assert(STEP(0x400, 1, 4, true, false, 0, 0) == Z8_JPEG_RESET_NONE);
    c[0] = 0x31;
    assert(STEP(4, 0x80000001, 4, true, false, 0, 0) == Z8_JPEG_RESET_NONE);
    puts("13 reset transition controls passed; no guest completion synthesized");
    return 0;
}
