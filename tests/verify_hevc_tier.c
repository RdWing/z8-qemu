/* SPDX-License-Identifier: GPL-2.0-or-later */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <glib.h>
#include "../qemu/nikon-wave5-codec.h"

static void verify(unsigned level, bool high)
{
    unsigned crop[4] = {0};
    WlHevcCodec *c = wl_video_open(1, 128, 128, 8, 30000, 1001,
                                  false, crop, 15, level, high);
    assert(c);
    GByteArray *headers = g_byte_array_new();
    uint32_t lengths[4];
    assert(wl_hevc_headers(c, headers, 0x3c, lengths));
    unsigned offset = 0;
    for (unsigned slot = 0; slot < 4; slot++) {
        assert(offset + 4 + lengths[slot] <= headers->len);
        assert(!memcmp(headers->data + offset, "\0\0\0\1", 4));
        if (slot == 1 || slot == 2) {
            uint8_t rbsp[4096]; unsigned count = 0, zeros = 0;
            assert(lengths[slot] < sizeof(rbsp));
            for (unsigned n = 0; n < lengths[slot]; n++) {
                uint8_t byte = headers->data[offset + 4 + n];
                if (zeros == 2 && byte == 3) { zeros = 0; continue; }
                rbsp[count++] = byte;
                zeros = byte == 0 ? zeros + 1 : 0;
            }
            unsigned profile = slot == 1 ? 6 : 3;
            assert(count > profile + 11);
            assert((rbsp[profile] & 31) == 1);
            assert(((rbsp[profile] >> 5) & 1) == high);
            assert(rbsp[profile + 11] == level);
        }
        offset += 4 + lengths[slot];
    }
    assert(offset == headers->len);
    g_byte_array_unref(headers); wl_hevc_close(c);
}

int main(void)
{
    verify(153, false); verify(153, true);
    verify(156, false); verify(156, true);
    assert(!wl_hevc_open(128, 128, 8, 30, 1, false, 15, 121, false));
    assert(!wl_hevc_open(128, 128, 8, 30, 1, false, 15, 90, true));
    assert(!wl_hevc_open(128, 128, 8, 30, 1, false, 15, 0, true));
    return 0;
}
