/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright (C) 2026 RdWing
 * Functional host HEVC/AVC decoder using installed public FFmpeg APIs.
 * No vendor microcode or camera inputs are included. */
#include <libavcodec/avcodec.h>
#include <libavutil/pixdesc.h>
typedef struct WlVideoDecBuffer {
    uint64_t plane[3];
    unsigned stride;
    bool set, interleaved, nv21;
} WlVideoDecBuffer;
/* Bounded programmable command queue; native CREATE requests four slots. */
#define WL_DEC_COMMAND_DEPTH 4
typedef struct WlVideoDecCommand {
    uint32_t rd, wr, options;
    unsigned instance;
    uint64_t submitted;
} WlVideoDecCommand;
typedef struct WlVideoDecode {
    AVCodecContext *context;
    AVCodecParserContext *parser;
    AVFrame *scratch;
    GQueue frames;
    unsigned width,height,depth,profile,fps_n,fps_d;
    uint64_t input_bytes,pictures;
    bool failed, stream_end, drained, picture_result, after_flush;
    WlVideoDecBuffer buffers[2][32];
    uint32_t write_bus, display_flags;
    uint64_t buffer_epoch[32];
    unsigned reference_for_linear[32];
    bool reference_bound[32];
    QEMUTimer *timer;
    void *owner, *instance;
    bool command_pending;
    WlVideoDecCommand commands[WL_DEC_COMMAND_DEPTH];
    unsigned command_count, command_capacity;
    uint32_t command_rd, command_wr, command_options;
    unsigned command_instance;
    unsigned output_index, output_type, output_bytes, output_crc;
    int output_poc;
    uint64_t outputs;
} WlVideoDecode;
static void wl_video_dec_close(WlVideoDecode *d)
{
    if(!d) { return; }
    if(d->timer) { timer_del(d->timer);timer_free(d->timer); }
    while(!g_queue_is_empty(&d->frames)) { AVFrame *f=g_queue_pop_head(&d->frames);av_frame_free(&f); }
    av_frame_free(&d->scratch);avcodec_free_context(&d->context);
    if(d->parser) { av_parser_close(d->parser); } g_free(d);
}
static WlVideoDecode *wl_video_dec_open(unsigned mode)
{
    enum AVCodecID id=mode==0?AV_CODEC_ID_HEVC:mode==2?AV_CODEC_ID_H264:AV_CODEC_ID_NONE;
    const AVCodec *codec=avcodec_find_decoder(id);if(!codec) { return NULL; }
    WlVideoDecode *d=g_new0(WlVideoDecode,1);g_queue_init(&d->frames);
    d->context=avcodec_alloc_context3(codec);d->parser=av_parser_init(id);d->scratch=av_frame_alloc();
    if(!d->context || !d->parser || !d->scratch) { wl_video_dec_close(d);return NULL; }
    d->context->thread_count=1;d->context->err_recognition=AV_EF_EXPLODE;
    if(avcodec_open2(d->context,codec,NULL)<0) { wl_video_dec_close(d);return NULL; }
    return d;
}
static bool wl_video_dec_receive(WlVideoDecode *d)
{
    for(;;) {
        int rc=avcodec_receive_frame(d->context,d->scratch);
        if(rc==AVERROR(EAGAIN) || rc==AVERROR_EOF) { return true; }
        if(rc<0 || g_queue_get_length(&d->frames)>=16 || d->scratch->format!=AV_PIX_FMT_YUV420P ||
            d->scratch->width<2 || d->scratch->height<2 || d->scratch->width>8192 || d->scratch->height>8192 || ((d->scratch->width|d->scratch->height)&1) || d->scratch->decode_error_flags ||
            (uint64_t)d->scratch->width*d->scratch->height>32*MiB) { return false; }
        AVFrame *copy=av_frame_clone(d->scratch);if(!copy) { return false; }
        g_queue_push_tail(&d->frames,copy);d->pictures++;av_frame_unref(d->scratch);
    }
}
static bool wl_video_dec_feed(WlVideoDecode *d,const uint8_t *input,unsigned bytes,unsigned *consumed)
{
    *consumed=0;if(!d || d->failed || !bytes || bytes>4*MiB) { return false; }
    uint8_t *padded=g_malloc0((size_t)bytes+AV_INPUT_BUFFER_PADDING_SIZE);memcpy(padded,input,bytes);
    unsigned loops=0,stalled=0;bool ok=true;
    while(*consumed<bytes && g_queue_is_empty(&d->frames) && loops++<4096) {
        uint8_t *packet_data=NULL;int packet_size=0;
        int used=av_parser_parse2(d->parser,d->context,&packet_data,&packet_size,padded+*consumed,
            bytes-*consumed,AV_NOPTS_VALUE,AV_NOPTS_VALUE,d->input_bytes+*consumed);
        if(used<0) { ok=false;break; }
        /* A parser-only flush can leave an empty access-unit boundary.
         * Retry that boundary once without submitting a decoder packet. */
        if(!used && !packet_size) { if(stalled++) { ok=false;break; }continue; }
        stalled=0;
        *consumed+=used;
        if(packet_size) {
            AVPacket *packet=av_packet_alloc();
            if(!packet || av_new_packet(packet,packet_size)<0) { av_packet_free(&packet);ok=false;break; }
            memcpy(packet->data,packet_data,packet_size);packet->pts=d->parser->output_picture_number;
            int rc=avcodec_send_packet(d->context,packet);av_packet_free(&packet);
            if(rc<0 || !wl_video_dec_receive(d)) { ok=false;break; }
        }
    }
    g_free(padded);d->input_bytes+=*consumed;
    d->width=d->context->width?d->context->width:d->parser->width;
    d->height=d->context->height?d->context->height:d->parser->height;
    int format=d->context->pix_fmt>=0?d->context->pix_fmt:d->parser->format;
    const AVPixFmtDescriptor *desc=av_pix_fmt_desc_get(format);
    d->depth=desc?desc->comp[0].depth:0;d->profile=d->context->profile<0?0:d->context->profile;
    if(d->context->framerate.num>0 && d->context->framerate.den>0) {
        d->fps_n=d->context->framerate.num;d->fps_d=d->context->framerate.den;
    }
    d->failed=!ok;return ok;
}

/* INIT_SEQ may contain exactly one access unit, with no next AUD yet.
 * Flush only the parser packet; keep the decoder open for later input.
 * Success still requires an actual strictly decoded frame/metadata. */
static bool wl_video_dec_finish_packet(WlVideoDecode *d)
{
    if(!d || d->failed) { return false; }
    uint8_t *data=NULL;int bytes=0;
    int used=av_parser_parse2(d->parser,d->context,&data,&bytes,NULL,0,
        AV_NOPTS_VALUE,AV_NOPTS_VALUE,d->input_bytes);
    if(used<0 || bytes<=0) { return false; }
    AVPacket *p=av_packet_alloc();if(!p || av_new_packet(p,bytes)<0) { av_packet_free(&p);return false; }
    memcpy(p->data,data,bytes);p->pts=d->parser->output_picture_number;int rc=avcodec_send_packet(d->context,p);av_packet_free(&p);
    if(rc<0 || !wl_video_dec_receive(d)) { d->failed=true;return false; }
    d->width=d->context->width;d->height=d->context->height;
    const AVPixFmtDescriptor *desc=av_pix_fmt_desc_get(d->context->pix_fmt);
    d->depth=desc?desc->comp[0].depth:0;d->profile=d->context->profile<0?0:d->context->profile;
    if(d->context->framerate.num>0 && d->context->framerate.den>0) {
        d->fps_n=d->context->framerate.num;d->fps_d=d->context->framerate.den;
    }
    return d->width && d->height && d->depth;
}

static bool wl_video_dec_end(WlVideoDecode *d)
{
    if(d->drained) { return true; }
    uint8_t *data=NULL;int bytes=0;
    int used=av_parser_parse2(d->parser,d->context,&data,&bytes,NULL,0,
        AV_NOPTS_VALUE,AV_NOPTS_VALUE,d->input_bytes);
    if(used<0) { return false; }
    if(bytes>0) {
        AVPacket *p=av_packet_alloc();if(!p || av_new_packet(p,bytes)<0) { av_packet_free(&p);return false; }
        memcpy(p->data,data,bytes);p->pts=d->parser->output_picture_number;
        int rc=avcodec_send_packet(d->context,p);av_packet_free(&p);
        if(rc<0 || !wl_video_dec_receive(d)) { return false; }
    }
    if(avcodec_send_packet(d->context,NULL)<0 || !wl_video_dec_receive(d)) { return false; }
    d->drained=true;return true;
}
