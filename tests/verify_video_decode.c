/* SPDX-License-Identifier: GPL-2.0-or-later
 * Generated lossless streams only; no camera firmware or saved media. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <glib.h>
#define MiB (1024u * 1024u)
typedef struct QEMUTimer QEMUTimer;
static void timer_del(QEMUTimer *timer) { (void)timer; }
static void timer_free(QEMUTimer *timer) { (void)timer; }
#include "../qemu/nikon-wave5-codec.h"
#include "../qemu/nikon-wave5-decode.h"

static void verify(unsigned mode)
{
    enum { W = 128, H = 128, FRAMES = 4 };
    unsigned crop[4] = {0};
    WlHevcCodec *enc = wl_video_open(mode, W, H, 8, 30, 1, true,
                                    crop, 15, 0, false);
    assert(enc);
    GByteArray *stream = g_byte_array_new();
    uint32_t lengths[4];
    assert(wl_hevc_headers(enc, stream, 0x3c, lengths));
    uint8_t pixels[W * H * 3 / 2];
    uint8_t *planes[3] = {pixels, pixels + W * H, pixels + W * H * 5 / 4};
    unsigned strides[3] = {W, W / 2, W / 2};
    for (unsigned n = 0; n < FRAMES; n++) {
        memset(planes[0], 40 + n * 31, W * H);
        memset(planes[1], 96 + n, W * H / 4);
        memset(planes[2], 160 - n, W * H / 4);
        unsigned nal;
        assert(wl_hevc_picture(enc, planes, strides, n, stream, &nal));
    }
    wl_hevc_close(enc);
    WlVideoDecode *dec = wl_video_dec_open(mode == 1 ? 0 : 2);
    assert(dec);
    unsigned offset = 0, frames = 0, attempts = 0;
    while (offset < stream->len || !g_queue_is_empty(&dec->frames)) {
        assert(++attempts < 128);
        if (g_queue_is_empty(&dec->frames)) {
            unsigned used;
            assert(wl_video_dec_feed(dec, stream->data + offset,
                                    stream->len - offset, &used));
            assert(used && used <= stream->len - offset);
            offset += used;
        }
        while (!g_queue_is_empty(&dec->frames)) {
            AVFrame *f = g_queue_pop_head(&dec->frames);
            assert(frames < FRAMES && f->width == W && f->height == H);
            for (unsigned p = 0; p < 3; p++) {
                unsigned rows = p ? H / 2 : H, cols = p ? W / 2 : W;
                uint8_t value = p == 0 ? 40 + frames * 31 :
                                p == 1 ? 96 + frames : 160 - frames;
                for (unsigned y = 0; y < rows; y++) {
                    for (unsigned x = 0; x < cols; x++) {
                        assert(f->data[p][(ptrdiff_t)y * f->linesize[p] + x] == value);
                    }
                }
            }
            frames++; av_frame_free(&f);
        }
    }
    assert(wl_video_dec_end(dec));
    while (!g_queue_is_empty(&dec->frames)) {
        AVFrame *f = g_queue_pop_head(&dec->frames);
        assert(frames == FRAMES - 1 && f->width == W && f->height == H);
        for (unsigned p = 0; p < 3; p++) {
            unsigned rows = p ? H / 2 : H, cols = p ? W / 2 : W;
            uint8_t value = p == 0 ? 40 + frames * 31 :
                            p == 1 ? 96 + frames : 160 - frames;
            for (unsigned y = 0; y < rows; y++) {
                for (unsigned x = 0; x < cols; x++) {
                    assert(f->data[p][(ptrdiff_t)y * f->linesize[p] + x] == value);
                }
            }
        }
        frames++; av_frame_free(&f);
    }
    assert(frames == FRAMES && dec->pictures == FRAMES && dec->drained);
    assert(wl_video_dec_end(dec) && g_queue_is_empty(&dec->frames));
    unsigned consumed = 99;
    assert(!wl_video_dec_feed(dec, stream->data, 0, &consumed) && consumed == 0);
    assert(!wl_video_dec_feed(dec, stream->data, 4 * MiB + 1, &consumed));
    wl_video_dec_close(dec); g_byte_array_unref(stream);
}
int main(void)
{
    assert(!wl_video_dec_open(1));
    verify(1); verify(3);
    return 0;
}
