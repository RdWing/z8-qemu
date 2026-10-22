/* Copyright (C) 2026 RdWing: Z8 adaptation. */
/*
 * Nikon Z 6III -- a JPEG stream decoded with libjpeg, for the JPEG cores'
 * decode mode (z8-jpeg-decode in z8-tools/z8lab_attach.c.in).
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 *
 * Two calls, no device state: the frame header (size and the chroma
 * sampling, in the cores' format numbering -- 1 = 4:2:2, the NV16 that
 * engine 0x15e2 encodes from (mode 0x31), 2 = 4:2:0), and the whole image
 * as interleaved full-resolution YCbCr, scaled down by 2^hs across and
 * 2^vs down: libjpeg's DCT scaling for the smaller of the two, nearest
 * pixel for what remains. A stream libjpeg rejects is a failure, never a
 * partial image. Uses the libjpeg API the capture models already link
 * (nikon-z8-jpeg.h).
 */

#ifndef HW_ARM_NIKON_Z8_JPEGDEC_H
#define HW_ARM_NIKON_Z8_JPEGDEC_H

#include <setjmp.h>
#include <jpeglib.h>

typedef struct Z8JpegDecError {
    struct jpeg_error_mgr api;
    jmp_buf jump;
} Z8JpegDecError;

static void z8_jpegdec_error(j_common_ptr codec)
{
    longjmp(((Z8JpegDecError *)codec->err)->jump, 1);
}

static void z8_jpegdec_quiet(j_common_ptr codec, int level)
{
}

/* The frame header: width, height and the sampling of a three-component
 * stream, 1 for 2x1 luma (4:2:2) and 2 for 2x2 (4:2:0). Anything else --
 * greyscale, 4:4:4, progressive -- is refused: nothing here says what the
 * cores report for it. */
static bool z8_jpegdec_info(const uint8_t *in, size_t len, unsigned *width,
                             unsigned *height, unsigned *format)
{
    struct jpeg_decompress_struct d;
    Z8JpegDecError err;
    volatile bool ok = false;

    d.err = jpeg_std_error(&err.api);
    err.api.error_exit = z8_jpegdec_error;
    err.api.emit_message = z8_jpegdec_quiet;
    if (setjmp(err.jump)) {
        jpeg_destroy_decompress(&d);
        return false;
    }
    jpeg_create_decompress(&d);
    jpeg_mem_src(&d, (unsigned char *)in, len);
    if (jpeg_read_header(&d, TRUE) == JPEG_HEADER_OK &&
        d.num_components == 3 && !d.progressive_mode &&
        d.comp_info[1].h_samp_factor == 1 && d.comp_info[1].v_samp_factor == 1 &&
        d.comp_info[2].h_samp_factor == 1 && d.comp_info[2].v_samp_factor == 1 &&
        d.comp_info[0].h_samp_factor == 2 &&
        (d.comp_info[0].v_samp_factor == 1 || d.comp_info[0].v_samp_factor == 2)) {
        *width = d.image_width;
        *height = d.image_height;
        *format = d.comp_info[0].v_samp_factor;
        ok = true;
    }
    jpeg_destroy_decompress(&d);
    return ok;
}

/* The image as width * height * 3 bytes of Y, Cb, Cr, scaled; the caller
 * frees it with g_free. NULL when libjpeg refuses the stream. */
static uint8_t *z8_jpegdec_ycc(const uint8_t *in, size_t len, unsigned hs,
                                unsigned vs, unsigned *width,
                                unsigned *height)
{
    struct jpeg_decompress_struct d;
    Z8JpegDecError err;
    uint8_t *volatile full = NULL;
    uint8_t *out;
    unsigned dw, dh, fx, fy, ow, oh;

    d.err = jpeg_std_error(&err.api);
    err.api.error_exit = z8_jpegdec_error;
    err.api.emit_message = z8_jpegdec_quiet;
    if (setjmp(err.jump)) {
        jpeg_destroy_decompress(&d);
        g_free(full);
        return NULL;
    }
    jpeg_create_decompress(&d);
    jpeg_mem_src(&d, (unsigned char *)in, len);
    jpeg_read_header(&d, TRUE);
    d.out_color_space = JCS_YCbCr;
    d.scale_num = 1;
    d.scale_denom = 1u << MIN(hs, vs);
    jpeg_start_decompress(&d);
    dw = d.output_width;
    dh = d.output_height;
    full = g_malloc((size_t)dw * dh * 3);
    while (d.output_scanline < dh) {
        JSAMPROW row = full + (size_t)d.output_scanline * dw * 3;

        jpeg_read_scanlines(&d, &row, 1);
    }
    jpeg_finish_decompress(&d);
    jpeg_destroy_decompress(&d);

    fx = 1u << (hs - MIN(hs, vs));
    fy = 1u << (vs - MIN(hs, vs));
    if (fx == 1 && fy == 1) {
        *width = dw;
        *height = dh;
        return full;
    }
    ow = (dw + fx - 1) / fx;
    oh = (dh + fy - 1) / fy;
    out = g_malloc((size_t)ow * oh * 3);
    for (unsigned y = 0; y < oh; y++) {
        for (unsigned x = 0; x < ow; x++) {
            memcpy(out + ((size_t)y * ow + x) * 3,
                   full + ((size_t)y * fy * dw + (size_t)x * fx) * 3, 3);
        }
    }
    g_free(full);
    *width = ow;
    *height = oh;
    return out;
}

#endif /* HW_ARM_NIKON_Z8_JPEGDEC_H */
