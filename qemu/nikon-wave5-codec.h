/* SPDX-License-Identifier: GPL-2.0-or-later
 * Authored functional HEVC/AVC backend. Uses installed public x265/x264 APIs;
 * no Nikon firmware, microcode or compression implementation is included.
 * Input planes are immutable actual DMA snapshots, never preview upshifts.
 */
#include <x265.h>
#include <x264.h>

typedef struct WlHevcCodec {
    const x265_api *api;
    x265_param *param;
    x265_encoder *encoder;
    x264_param_t *avc_param;
    x264_t *avc_encoder;
    unsigned codec_mode; /* Explicit Wave5 convention: 1 HEVC, 3 AVC. */
    unsigned width, height, depth;
    uint64_t frames;
} WlHevcCodec;

static void wl_hevc_close(WlHevcCodec *codec)
{
    if (!codec) { return; }
    if (codec->avc_encoder) { x264_encoder_close(codec->avc_encoder); }
    if (codec->avc_param) {
        x264_param_cleanup(codec->avc_param);
        g_free(codec->avc_param);
    }
    if (codec->encoder) { codec->api->encoder_close(codec->encoder); }
    if (codec->param) { codec->api->param_free(codec->param); }
    g_free(codec);
}

static WlHevcCodec *wl_hevc_open(unsigned width, unsigned height, unsigned depth,
                               unsigned fps_n, unsigned fps_d, bool lossless,
                               unsigned keyframe_period)
{
    if (!width || !height || (width | height) & 1 || width > 8192 || height > 8192 ||
        (depth != 8 && depth != 10) || !fps_n || !fps_d) { return NULL; }
    const x265_api *api = x265_api_get(depth);
    if (!api || api->bit_depth != depth || api->sizeof_param != sizeof(x265_param) ||
        api->sizeof_picture != sizeof(x265_picture)) { return NULL; }
    WlHevcCodec *codec = g_new0(WlHevcCodec, 1);
    codec->api = api;
    codec->param = api->param_alloc();
    if (!codec->param || api->param_default_preset(codec->param, "ultrafast", "zerolatency") < 0) {
        wl_hevc_close(codec); return NULL;
    }
    x265_param *p = codec->param;
    p->sourceWidth = width; p->sourceHeight = height;
    p->internalCsp = X265_CSP_I420; p->internalBitDepth = depth;
    p->fpsNum = fps_n; p->fpsDenom = fps_d;
    p->frameNumThreads = 1;
    p->bframes = 0; p->lookaheadDepth = 0;
    p->bRepeatHeaders = 0; p->bAnnexB = 1;
    /* Native movie packets retain the advertised AUD length on every
     * access unit. Omitting it lets the mux overwrite VCL bytes at +7. */
    p->bEnableAccessUnitDelimiters = 1;
    if (keyframe_period) {
        p->keyframeMax = keyframe_period; p->keyframeMin = 1;
        p->scenecutThreshold = 0; p->bOpenGOP = 0;
    }
    p->bEnableWavefront = 0; p->bEnablePsnr = 0; p->bEnableSsim = 0;
    p->logLevel = X265_LOG_ERROR;
    p->bLossless = lossless;
    p->rc.rfConstant = 18;
    if (api->param_parse(p, "pools", "none") < 0 ||
        api->param_apply_profile(p, depth == 10 ? "main10" : "main") < 0) {
        wl_hevc_close(codec); return NULL;
    }
    codec->encoder = api->encoder_open(p);
    if (!codec->encoder) { wl_hevc_close(codec); return NULL; }
    codec->width = width; codec->height = height; codec->depth = depth; codec->codec_mode = 1;
    return codec;
}

static WlHevcCodec *wl_video_open(unsigned mode, unsigned width, unsigned height, unsigned depth,
                                unsigned fps_n, unsigned fps_d, bool lossless,
                                const unsigned crop[4], unsigned keyframe_period)
{
    if (mode == 1) { return wl_hevc_open(width, height, depth, fps_n, fps_d, lossless, keyframe_period); }
    if (mode != 3 || !width || !height || (width | height) & 1 ||
        width > 8192 || height > 8192 || (depth != 8 && depth != 10) || !fps_n || !fps_d) {
        return NULL;
    }
    WlHevcCodec *codec = g_new0(WlHevcCodec, 1);
    codec->avc_param = g_new0(x264_param_t, 1);
    x264_param_t *p = codec->avc_param;
    if (x264_param_default_preset(p, "ultrafast", "zerolatency") < 0) {
        wl_hevc_close(codec); return NULL;
    }
    p->i_width = width; p->i_height = height; p->i_bitdepth = depth;
    p->i_csp = X264_CSP_I420 | (depth > 8 ? X264_CSP_HIGH_DEPTH : 0);
    /* Keep the complete coded DMA surface. SPS cropping controls the
     * displayed rectangle, including each 4:2:0 chroma edge. */
    p->crop_rect.i_left = crop[0]; p->crop_rect.i_top = crop[1];
    p->crop_rect.i_right = crop[2]; p->crop_rect.i_bottom = crop[3];
    p->i_fps_num = fps_n; p->i_fps_den = fps_d;
    p->i_timebase_num = fps_d; p->i_timebase_den = fps_n;
    p->i_threads = 1; p->i_lookahead_threads = 1;
    p->i_bframe = 0; p->rc.i_lookahead = 0; p->b_vfr_input = 0;
    p->b_repeat_headers = 0; p->b_annexb = 1; p->b_aud = 1;
    p->i_log_level = X264_LOG_ERROR;
    if (keyframe_period) {
        p->i_keyint_max = keyframe_period; p->i_keyint_min = 1;
        p->i_scenecut_threshold = 0; p->b_open_gop = 0;
    }
    if (lossless) { p->rc.i_rc_method = X264_RC_CQP; p->rc.i_qp_constant = 0; }
    else { p->rc.i_rc_method = X264_RC_CRF; p->rc.f_rf_constant = 18; }
    if (x264_param_apply_profile(p, lossless ? "high444" : depth == 10 ? "high10" : "high") < 0) {
        wl_hevc_close(codec); return NULL;
    }
    codec->avc_encoder = x264_encoder_open(p);
    if (!codec->avc_encoder) { wl_hevc_close(codec); return NULL; }
    codec->width = width; codec->height = height; codec->depth = depth; codec->codec_mode = mode;
    return codec;
}

static bool wl_header_nal(GByteArray *output, const uint8_t *data,
                          unsigned bytes, uint32_t *length)
{
    unsigned prefix = bytes >= 4 && !memcmp(data, "\0\0\0\1", 4) ? 4 :
                      bytes >= 3 && !memcmp(data, "\0\0\1", 3) ? 3 : 0;
    if (!prefix || bytes <= prefix) { return false; }
    /* The native header report counts NAL bytes without the start code.
     * Native consumers add exactly four bytes when walking the stream. */
    *length = bytes - prefix;
    g_byte_array_append(output, (const uint8_t *)"\0\0\0\1", 4);
    g_byte_array_append(output, data + prefix, *length);
    return true;
}

static bool wl_hevc_headers(WlHevcCodec *codec, GByteArray *output,
                            unsigned options, uint32_t lengths[4])
{
    if (!codec || !(options & 0x3c)) { return false; }
    const uint8_t *data[4] = {0};
    unsigned bytes[4] = {0};
    /* Requested AUD is first, followed by VPS/SPS/PPS. The AUD describes
     * the first intra picture. These are public Annex B syntax bytes;
     * parameter sets themselves come from the selected host codec. */
    static const uint8_t hevc_aud[] = {0, 0, 0, 1, 0x46, 1, 0x10};
    static const uint8_t avc_aud[] = {0, 0, 0, 1, 9, 0x10};
    data[0] = codec->codec_mode == 3 ? avc_aud : hevc_aud;
    bytes[0] = codec->codec_mode == 3 ? sizeof(avc_aud) : sizeof(hevc_aud);
    memset(lengths, 0, 4 * sizeof(*lengths));
    if (codec->codec_mode == 3) {
        x264_nal_t *nals = NULL; int count = 0;
        if (x264_encoder_headers(codec->avc_encoder, &nals, &count) < 0 || count <= 0) { return false; }
        for (int i = 0; i < count; i++) {
            unsigned slot = nals[i].i_type == 7 ? 2 : nals[i].i_type == 8 ? 3 : 4;
            if (slot < 4) { data[slot] = nals[i].p_payload; bytes[slot] = nals[i].i_payload; }
        }
    } else {
        x265_nal *nals = NULL; uint32_t count = 0;
        if (codec->api->encoder_headers(codec->encoder, &nals, &count) < 0 || !count) { return false; }
        for (unsigned i = 0; i < count; i++) {
            unsigned type = nals[i].type;
            if (type >= 32 && type <= 34) {
                data[type - 31] = nals[i].payload; bytes[type - 31] = nals[i].sizeBytes;
            }
        }
    }
    const unsigned masks[] = {0x20, 4, 8, 0x10};
    for (unsigned slot = 0; slot < 4; slot++) {
        if (!(options & masks[slot]) || (slot == 1 && codec->codec_mode == 3)) { continue; }
        if (!data[slot] || !wl_header_nal(output, data[slot], bytes[slot], &lengths[slot])) { return false; }
    }
    return output->len != 0;
}

static bool wl_hevc_picture(WlHevcCodec *codec, uint8_t *planes[3], const unsigned strides[3],
                            uint64_t pts, GByteArray *output, unsigned *nal_type)
{
    if (!codec || !planes[0] || !planes[1] || !planes[2]) { return false; }
    if (codec->codec_mode == 3) {
        x264_picture_t input, result;
        x264_picture_init(&input); x264_picture_init(&result);
        input.img.i_csp = X264_CSP_I420 | (codec->depth > 8 ? X264_CSP_HIGH_DEPTH : 0);
        input.img.i_plane = 3; input.i_pts = pts;
        for (unsigned i = 0; i < 3; i++) {
            input.img.plane[i] = planes[i]; input.img.i_stride[i] = strides[i];
        }
        x264_nal_t *nals = NULL; int count = 0;
        if (x264_encoder_encode(codec->avc_encoder, &nals, &count, &input, &result) <= 0 || count <= 0) {
            return false;
        }
        *nal_type = nals[0].i_type;
        for (int i = 0; i < count; i++) {
            uint32_t length;
            if (!wl_header_nal(output, nals[i].p_payload, nals[i].i_payload, &length)) {
                return false;
            }
            if (nals[i].i_type == NAL_SLICE || nals[i].i_type == NAL_SLICE_IDR) { *nal_type = nals[i].i_type; }
        }
        codec->frames++; return true;
    }
    x265_picture *input = codec->api->picture_alloc();
    x265_picture *result = codec->api->picture_alloc();
    if (!input || !result) {
        if (input) { codec->api->picture_free(input); }
        if (result) { codec->api->picture_free(result); }
        return false;
    }
    codec->api->picture_init(codec->param, input);
    codec->api->picture_init(codec->param, result);
    input->bitDepth = codec->depth; input->pts = pts;
    for (unsigned i = 0; i < 3; i++) {
        input->planes[i] = planes[i]; input->stride[i] = strides[i];
    }
    x265_nal *nals = NULL; uint32_t count = 0;
    int produced = codec->api->encoder_encode(codec->encoder, &nals, &count, input, result);
    bool valid = produced == 1 && count != 0;
    if (valid) {
        *nal_type = nals[0].type;
        for (unsigned i = 0; i < count; i++) {
            uint32_t length;
            if (!wl_header_nal(output, nals[i].payload, nals[i].sizeBytes, &length)) {
                valid = false; break;
            }
            if (nals[i].type < 32) { *nal_type = nals[i].type; }
        }
        if (valid) { codec->frames++; }
    }
    codec->api->picture_free(input); codec->api->picture_free(result);
    return valid;
}
