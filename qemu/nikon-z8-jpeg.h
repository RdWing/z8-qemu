/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright (C) 2026 RdWing */
/* WonderLantern functional JPEG backend, independent of camera firmware.
 * Input: bounded full-range NV16 RAM and explicit natural-order quantizers.
 * Output: actual baseline JPEG bytes; this helper emits no device status.
 * Uses the separately installed open-source libjpeg-turbo C API. */
#ifndef WONDERLANTERN_NV16_JPEG_H
#define WONDERLANTERN_NV16_JPEG_H

#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <setjmp.h>
#include <jpeglib.h>

typedef struct WonderLanternJPEGError {
    struct jpeg_error_mgr api;
    jmp_buf jump;
} WonderLanternJPEGError;

typedef struct WonderLanternJPEGContext {
    struct jpeg_compress_struct codec;
    WonderLanternJPEGError error;
    unsigned char *output;
    unsigned long output_bytes;
    unsigned char *row;
} WonderLanternJPEGContext;

static void wonderlantern_jpeg_error(j_common_ptr codec)
{
    WonderLanternJPEGError *error = (WonderLanternJPEGError *)codec->err;
    longjmp(error->jump, 1);
}

/* Caller owns the returned malloc buffer; failure returns no partial bytes.
 * Both full input planes and the maximum output size must be explicit. */
static int wonderlantern_nv16_jpeg_scaled(const uint8_t *y, size_t y_bytes,
                                  const uint8_t *uv, size_t uv_bytes,
                                  unsigned width, unsigned height, unsigned stride,
                                  const uint8_t quantizers[2][64], size_t capacity,
                                  unsigned scale_shift,
                                  unsigned char **output, size_t *output_bytes)
{
    *output = NULL; *output_bytes = 0;
    if (!y || !uv || !quantizers || !width || !height || (width & 1) ||
        width > 16384 || height > 16384 || stride < width || stride > 32768 ||
        (size_t)stride * height > 64u * 1024u * 1024u ||
        y_bytes != (size_t)stride * height || uv_bytes != y_bytes ||
        !capacity || capacity > 128u * 1024u * 1024u || scale_shift > 2 ||
        !(width >> scale_shift) || !(height >> scale_shift)) { return 0; }
    /* Declared functional nearest input sampling for original codec scale2.
     * Source remains complete even-width NV16; encoded JPEG width may be odd.
     * No guest input, intermediate RAM or allocator metadata is changed. */
    unsigned encoded_width = width >> scale_shift;
    for (unsigned table = 0; table < 2; table++) {
        for (unsigned at = 0; at < 64; at++) {
            if (!quantizers[table][at]) { return 0; }
        }
    }
    WonderLanternJPEGContext *ctx = calloc(1, sizeof(*ctx));
    if (!ctx) { return 0; }
    ctx->codec.err = jpeg_std_error(&ctx->error.api);
    ctx->error.api.error_exit = wonderlantern_jpeg_error;
    if (setjmp(ctx->error.jump)) {
        jpeg_destroy_compress(&ctx->codec);
        free(ctx->row); free(ctx->output); free(ctx); return 0;
    }
    jpeg_create_compress(&ctx->codec);
    jpeg_mem_dest(&ctx->codec, &ctx->output, &ctx->output_bytes);
    ctx->codec.image_width = encoded_width;
    ctx->codec.image_height = height >> scale_shift;
    ctx->codec.input_components = 3; ctx->codec.in_color_space = JCS_YCbCr;
    jpeg_set_defaults(&ctx->codec);
    ctx->codec.comp_info[0].h_samp_factor = 2;
    ctx->codec.comp_info[0].v_samp_factor = 1;
    for (unsigned component = 1; component < 3; component++) {
        ctx->codec.comp_info[component].h_samp_factor = 1;
        ctx->codec.comp_info[component].v_samp_factor = 1;
    }
    for (unsigned table = 0; table < 2; table++) {
        unsigned int values[64];
        for (unsigned at = 0; at < 64; at++) { values[at] = quantizers[table][at]; }
        jpeg_add_quant_table(&ctx->codec, table, values, 100, TRUE);
    }
    ctx->codec.optimize_coding = TRUE;
    ctx->codec.dct_method = JDCT_ISLOW;
    ctx->row = malloc((size_t)encoded_width * 3);
    if (!ctx->row) {
        jpeg_destroy_compress(&ctx->codec); free(ctx->output); free(ctx); return 0;
    }
    jpeg_start_compress(&ctx->codec, TRUE);
    while (ctx->codec.next_scanline < ctx->codec.image_height) {
        size_t base = ((size_t)ctx->codec.next_scanline << scale_shift) * stride;
        for (unsigned x = 0; x < encoded_width; x++) {
            unsigned source_x = x << scale_shift;
            ctx->row[x * 3] = y[base + source_x];
            ctx->row[x * 3 + 1] = uv[base + (source_x & ~1u)];
            ctx->row[x * 3 + 2] = uv[base + (source_x & ~1u) + 1];
        }
        JSAMPROW row = ctx->row;
        jpeg_write_scanlines(&ctx->codec, &row, 1);
    }
    jpeg_finish_compress(&ctx->codec);
    jpeg_destroy_compress(&ctx->codec); free(ctx->row);
    if (ctx->output_bytes > capacity) { free(ctx->output); free(ctx); return 0; }
    *output = ctx->output; *output_bytes = ctx->output_bytes;
    free(ctx); return 1;
}

static int wonderlantern_nv16_jpeg(const uint8_t *y, size_t y_bytes,
                                  const uint8_t *uv, size_t uv_bytes,
                                  unsigned width, unsigned height, unsigned stride,
                                  const uint8_t quantizers[2][64], size_t capacity,
                                  unsigned char **output, size_t *output_bytes)
{
    return wonderlantern_nv16_jpeg_scaled(y, y_bytes, uv, uv_bytes, width, height,
        stride, quantizers, capacity, 0, output, output_bytes);
}

#endif
