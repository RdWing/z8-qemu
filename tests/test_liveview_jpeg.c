/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Synthetic codec controls; no firmware or camera input. Compile once with
 * the imported baseline header and once with the adapted header. */
#include <assert.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#ifndef JPEG_HEADER
#define JPEG_HEADER "../qemu/nikon-z8-jpeg.h"
#endif
#include JPEG_HEADER

static void save(const char *dir, const char *name, const unsigned char *p,
                  size_t bytes)
{
    char path[4096];
    int n = snprintf(path, sizeof(path), "%s/%s", dir, name);
    assert(n > 0 && (size_t)n < sizeof(path));
    FILE *f = fopen(path, "wb");
    assert(f && fwrite(p, 1, bytes, f) == bytes && fclose(f) == 0);
}

int main(int argc, char **argv)
{
    enum { W = 640, H = 424, STRIDE = 656, PLANE = STRIDE * H };
    uint8_t *y = malloc(PLANE), *uv = malloc(PLANE);
    uint8_t q[2][64];
    unsigned char *out = NULL;
    size_t bytes = 0;

    assert(argc == 2 && y && uv);
    memset(q, 6, sizeof(q));
    for (unsigned r = 0; r < H; r++) {
        for (unsigned c = 0; c < STRIDE; c++) {
            y[r * STRIDE + c] = 32 + (r + c) % 192;
            uv[r * STRIDE + c] = (c & 1) ? 80 + r % 80 : 128;
        }
    }
    for (unsigned scale = 0; scale < 3; scale++) {
        char name[40];
        assert(wonderlantern_nv16_jpeg_scaled(y, PLANE, uv, PLANE, W, H,
            STRIDE, q, 2 * 1024 * 1024, scale, &out, &bytes));
        assert(out && bytes > 100 && out[0] == 0xff && out[1] == 0xd8);
        snprintf(name, sizeof(name), "nv16-scale%u.jpg", scale);
        save(argv[1], name, out, bytes);
        free(out);
    }
    assert(wonderlantern_nv16_jpeg(y, PLANE, uv, PLANE, W, H, STRIDE,
                                  q, 2 * 1024 * 1024, &out, &bytes));
    free(out);
#ifdef TEST_NV12
    /* Allocate exactly the half-height chroma plane; ASan catches reads
     * made with the old full-height UV addressing. Distinct vertical bands
     * expose incorrectly doubled/dropped rows after decoding. */
    free(uv);
    uv = malloc(PLANE / 2);
    assert(uv);
    memset(y, 100, PLANE);
    for (unsigned r = 0; r < H / 2; r++) {
        for (unsigned c = 0; c < STRIDE; c += 2) {
            uv[r * STRIDE + c] = r < 100 ? 80 : 170;
            uv[r * STRIDE + c + 1] = r < 100 ? 170 : 80;
        }
    }
    assert(wonderlantern_nv12_jpeg(y, PLANE, uv, PLANE / 2, W, H,
                                   STRIDE, q, 2 * 1024 * 1024, &out, &bytes));
    struct jpeg_decompress_struct decoder;
    struct jpeg_error_mgr err;
    decoder.err = jpeg_std_error(&err);
    jpeg_create_decompress(&decoder);
    jpeg_mem_src(&decoder, out, bytes);
    assert(jpeg_read_header(&decoder, TRUE) == JPEG_HEADER_OK);
    assert(decoder.image_width == W && decoder.image_height == H);
    assert(decoder.comp_info[0].h_samp_factor == 2 &&
           decoder.comp_info[0].v_samp_factor == 2 &&
           decoder.comp_info[1].h_samp_factor == 1 &&
           decoder.comp_info[1].v_samp_factor == 1);
    decoder.out_color_space = JCS_YCbCr;
    assert(jpeg_start_decompress(&decoder));
    unsigned char row[W * 3];
    while (decoder.output_scanline < H) {
        unsigned r = decoder.output_scanline;
        JSAMPROW rows[] = { row };
        assert(jpeg_read_scanlines(&decoder, rows, 1) == 1);
        if (r == 50 || r == 300) {
            assert(abs((int)row[90] - 100) <= 3);
            assert(abs((int)row[91] - (r < 200 ? 80 : 170)) <= 3);
            assert(abs((int)row[92] - (r < 200 ? 170 : 80)) <= 3);
        }
    }
    assert(jpeg_finish_decompress(&decoder));
    jpeg_destroy_decompress(&decoder);
    save(argv[1], "nv12.jpg", out, bytes);
    free(out);
    assert(!wonderlantern_nv12_jpeg(y, PLANE, uv, PLANE / 2 - 1, W, H,
                                    STRIDE, q, 2 * 1024 * 1024, &out, &bytes));
    assert(!out && !bytes);
    assert(!wonderlantern_nv12_jpeg(y, PLANE, uv, PLANE / 2, W, H,
                                    STRIDE, q, 1, &out, &bytes));
    assert(!out && !bytes);
    assert(!wonderlantern_nv12_jpeg(y, PLANE, uv, PLANE / 2, W, H - 1,
                                    STRIDE, q, 2 * 1024 * 1024, &out, &bytes));
    q[0][0] = 0;
    assert(!wonderlantern_nv12_jpeg(y, PLANE, uv, PLANE / 2, W, H,
                                    STRIDE, q, 2 * 1024 * 1024, &out, &bytes));
    assert(!out && !bytes);
#endif
    free(y);
    free(uv);
    puts("codec controls passed; synthetic RAM only");
    return 0;
}
