/* Copyright (C) 2026 RdWing: Z8 adaptation. */
/* SPDX-License-Identifier: GPL-2.0-or-later
 * Functional DSP boot interface; no CEVA instructions are executed.
 * Original ZR ARM path:40e2ee50 ->40e0a71c ->40e0aca0 ->40e98130.
 * Port1 receives messages; port0 acknowledges outgoing messages. The
 * descriptor encodes a mailbox slot, not the nine-word payload length.
 */
#define WL_DSP_BOOT_CHANNELS 4
#define WL_DSP_BOOT_SLOTS 8
#define WL_DSP_BOOT_DELAY_NS 1000000
#define WL_DSP_SESSION_ALLOCATION_BYTES 0x56e40
#define WL_DSP_SESSION_WORKSPACE_BYTES 0x44e00
#define WL_DSP_MODULE_WORKSPACE_BYTES 0x384d00
#include <zlib.h>
#include "nikon-expeed-motion.h"
#include "nikon-expeed-correction.h"
typedef struct WlDspBootChannel {
    QEMUTimer *timer, *tx_timer;
    QEMUTimer *init_timer;
    NikonZ8State *owner;
    unsigned channel;
    qemu_irq irq, tx_irq;
    uint32_t claims[8], lengths[8], destinations[8], tx[8][16], rx[16], core_control;
    uint32_t tx_written[8], last_tx[16], last_tx_written, last_tx_control;
    uint32_t last_tx_claim, last_tx_route, last_tx_destination;
    unsigned tx_slot;
    uint32_t lpcm_mode,lpcm_input,lpcm_output,lpcm_reply[9];
    uint64_t lpcm_jobs,lpcm_input_bytes,lpcm_output_bytes,lpcm_rejects;
    bool reset_held, scheduled, booted, rx_pending, tx_scheduled, tx_pending;
    uint64_t requests, replies, acknowledgements, cancelled;
    uint64_t tx_requests, tx_confirmations, tx_acks, tx_cancelled;
    bool init_scheduled, init_ready, init_configured, rx_is_init;
    uint32_t init_opcode, init_group, init_program_bytes[2], init_crc[2];
    uint8_t *init_program[2];
    uint64_t init_parameter, init_workspace;
    uint32_t init_workspace_bytes;
    uint64_t init_requests, init_completed, init_replies, init_acks, init_cancelled;
    uint32_t init_reject_code;
    uint64_t init_debug_parameter, init_debug_window[3], init_debug_header[9];
    WlMotionJob motion;
    WlCorrectionWork correction;
    bool init_is_correction;
} WlDspBootChannel;
typedef struct WlDspBootState {
    WlDspBootChannel channels[4];
} WlDspBootState;
static const hwaddr wl_dsp_csrs[] = {0x1c800000, 0x1d800000, 0x1fc00000,0x1b800000};
static const hwaddr wl_dsp_mailboxes[] = {0x1c802000, 0x1d802000, 0x1fc02000,0x1b802000};
static const unsigned wl_dsp_rx_irqs[] = {78, 82, 74,87};

static void dsp_boot_irq_update(WlDspBootChannel *d)
{
    if (d->irq) { qemu_set_irq(d->irq, d->rx_pending); }
    if (d->tx_irq) { qemu_set_irq(d->tx_irq, d->tx_pending); }
}
/* Explicit functional session initialization. Program data remains opaque;
 * no CEVA/NeuPro instruction or inference is executed. Unknown processing
 * commands do not acquire a successful result from this backend. */
static bool dsp_session_ram_address(NikonZ8State *s, unsigned channel,
                                    uint32_t local, uint32_t bytes, uint64_t *physical)
{
    if (!s->dsp_ram_aperture_fixture || !bytes || channel >= 3) { return false; }
    uint64_t *window = s->bus_windows[3 + channel][1][0];
    uint64_t ram_bytes = MACHINE(s)->ram_size;
    if (window[0] != 0x40000000 || window[1] != (UINT64_C(1) << 36) - ram_bytes ||
            (window[2] != 0 && window[2] != UINT64_C(0x200000000)) ||
            local < 0x40000000 || (uint64_t)local - 0x40000000 >= ram_bytes ||
            bytes > ram_bytes - ((uint64_t)local - 0x40000000)) { return false; }
    /* Original40ec1930/41381b9c maps cached CPUA0 to native SDRAM2G.
     * Both the declared initial0 offset and configured2G backing address
     * refer to this lab's same mapped work RAM. Other offsets stay strict. */
    *physical = UINT64_C(0xa00000000) + local - 0x40000000;
    return dma_ram_range(s, *physical, bytes);
}
static bool dsp_session_overlap(uint64_t a, uint32_t na, uint64_t b, uint32_t nb)
{ return a < b + nb && b < a + na; }
static bool dsp_correction_submit(NikonZ8State *s, WlDspBootChannel *d,
                                  const uint32_t *words, uint32_t written)
{
    WlCorrectionWork *c = &d->correction; c->reject = 1;
    memcpy(d->init_debug_window, s->bus_windows[3 + d->channel][1][0], sizeof(d->init_debug_window));
    if (!s->dsp_correction_init_model || d->channel || written != 15 || words[2] || words[3] ||
            d->init_scheduled || d->init_ready || d->rx_is_init || c->queued || c->rx) { return false; }
    if (words[0] == 1) {
        c->reject = 2;
        if (!c->configured) { return false; }
    } else if (words[0] == 0) {
        uint8_t header[WL_CPC_PARAMETER_BYTES], payload[WL_CPC_CALIBRATION_BYTES];
        uint64_t parameter, calibration;
        c->reject = 3;
        if (!dsp_session_ram_address(s, 0, words[1], sizeof(header), &parameter) ||
                address_space_read(&address_space_memory, parameter, MEMTXATTRS_UNSPECIFIED,
                    header, sizeof(header)) != MEMTX_OK) { return false; }
        c->reject = 4;
        uint64_t local = ldq_le_p(header);
        if (local > UINT32_MAX || ldl_le_p(header + 32) != sizeof(payload) ||
                ldl_le_p(header + 36) != 1 || ldl_le_p(header + 40) != sizeof(payload) ||
                ldl_le_p(header + 52) != 16 || ldq_le_p(header + 56) != UINT64_C(0xe0000000) ||
                ldl_le_p(header + 108) != 1 || ldl_le_p(header + 128)) { return false; }
        for (unsigned i = 8; i < 32; i++) { if (header[i]) { return false; } }
        for (unsigned i = 44; i < 52; i++) { if (header[i]) { return false; } }
        for (unsigned i = 64; i < 88; i++) { if (header[i]) { return false; } }
        for (unsigned i = 100; i < 108; i++) { if (header[i]) { return false; } }
        for (unsigned i = 112; i < 124; i++) { if (header[i]) { return false; } }
        uint32_t w = ldl_le_p(header + 88), h = ldl_le_p(header + 92), pitch = ldl_le_p(header + 96);
        uint64_t bytes = (uint64_t)pitch * h;
        c->reject = 5;
        if (w < 4 || h < 4 || w > 16384 || h > 16384 || pitch < w || pitch > 4 * w + 512 ||
                bytes > 512 * MiB || bytes != ldl_le_p(header + 124)) { return false; }
        c->reject = 6;
        if (!dsp_session_ram_address(s, 0, local, sizeof(payload), &calibration) ||
                dsp_session_overlap(parameter, sizeof(header), calibration, sizeof(payload)) ||
                address_space_read(&address_space_memory, calibration, MEMTXATTRS_UNSPECIFIED,
                    payload, sizeof(payload)) != MEMTX_OK) { return false; }
        /* Clamp the count to the actual50-record packet bound. Each accepted
         * coordinate produces an owned numerical neighbor plan at completion. */
        c->reject = 7;
        unsigned count = MIN(lduw_le_p(payload), 50);
        for (unsigned i = 0; i < count; i++) {
            if (lduw_le_p(payload + 2 + i * 30) >= w ||
                    lduw_le_p(payload + 4 + i * 30) >= h) { return false; }
        }
        memcpy(c->parameters, header, sizeof(header)); memcpy(c->payload, payload, sizeof(payload));
        c->parameter = parameter; c->calibration = calibration;
        c->width = w; c->height = h; c->stride = pitch; c->frame_bytes = bytes;
        c->raw_count = lduw_le_p(payload);
        c->parameter_crc = crc32(0, header, sizeof(header));
        c->calibration_crc = crc32(0, payload, sizeof(payload));
    } else { c->reject = 8; return false; }
    c->reject = 0; c->opcode = words[0]; c->queued = true; c->requests++;
    d->init_is_correction = true;
    d->init_opcode = words[0]; d->init_group = 0;
    d->init_parameter = c->parameter; d->init_workspace = 0; d->init_workspace_bytes = 0;
    d->init_configured = false; d->init_requests++; d->init_scheduled = true;
    timer_mod(d->init_timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + WL_DSP_BOOT_DELAY_NS);
    return true;
}
static void dsp_motion_try_reply(WlDspBootChannel *d)
{
    WlMotionJob *m = &d->motion;
    if (!m->ready || d->reset_held || d->rx_pending || d->tx_scheduled ||
            d->tx_pending || d->claims[d->tx_slot] || d->claims[0]) { return; }
    memset(d->rx, 0, sizeof(d->rx));
    d->rx[0] = m->opcode; d->rx[2] = m->group;
    d->rx_pending = m->rx = true; m->ready = false; m->replies++;
    dsp_boot_irq_update(d);
}
static void dsp_motion_complete(void *opaque)
{
    WlDspBootChannel *d = opaque; WlMotionJob *m = &d->motion;
    if (!m->scheduled || d->reset_held) { return; }
    if (m->opcode == 0x18) {
        WlMovingWork *w = &m->moving;
        static const unsigned bpp[8] = {1, 1, 4, 2, 2, 2, 2, 2};
        uint8_t planes[8][4096], tail[16], scratch[2048];
        moving_compute(w, planes, tail, scratch);
        uint64_t written = 0;
        for (unsigned plane = 0; plane < 8; plane++) {
            for (unsigned row = 0; row < 32; row++) {
                unsigned bytes = 32 * bpp[plane];
                if (address_space_write(&address_space_memory,
                        w->destinations[plane] + row * w->pitches[plane], MEMTXATTRS_UNSPECIFIED,
                        planes[plane] + row * bytes, bytes) != MEMTX_OK) { goto moving_failed; }
                written += bytes;
            }
        }
        if (address_space_write(&address_space_memory, w->workspace, MEMTXATTRS_UNSPECIFIED,
                scratch, sizeof(scratch)) != MEMTX_OK ||
            address_space_write(&address_space_memory, m->result + 0xc0, MEMTXATTRS_UNSPECIFIED,
                tail, sizeof(tail)) != MEMTX_OK) { goto moving_failed; }
        m->result_crc = crc32(0, tail, sizeof(tail));
        for (unsigned i = 0; i < 2; i++) { g_free(w->input[i]); w->input[i] = NULL; }
        m->completed++; m->bytes_read += m->input_bytes;
        m->bytes_written += written + sizeof(scratch) + sizeof(tail);
        m->features = w->valid_cells; m->tracks = w->foreground_cells;
        m->inliers = 0; m->dx = m->dy = 0;
        m->scheduled = false; m->ready = true;
        dsp_motion_try_reply(d);
        return;
moving_failed:
        m->scheduled = false;
        for (unsigned i = 0; i < 2; i++) { g_free(w->input[i]); w->input[i] = NULL; }
        unknown_access(d->owner, wl_dsp_mailboxes[d->channel] + 0x108, 1, 4, true);
        return;
    }
    uint8_t result[WL_MOTION_RESULT_BYTES] = {0};
    motion_compute(m, result);
    if (address_space_write(&address_space_memory, m->result, MEMTXATTRS_UNSPECIFIED,
            result, m->result_bytes) != MEMTX_OK) {
        m->scheduled = false;
        unknown_access(d->owner, wl_dsp_mailboxes[d->channel] + 0x108, 1, 4, true);
        return;
    }
    m->result_crc = crc32(0, result, m->result_bytes);
    m->completed++; m->bytes_read += m->input_bytes; m->bytes_written += m->result_bytes;
    m->scheduled = false; m->ready = true;
    dsp_motion_try_reply(d);
}
static bool dsp_motion_submit(NikonZ8State *s, WlDspBootChannel *d,
                               const uint32_t *words, uint32_t written)
{
    WlMotionJob *m = &d->motion; m->reject = 1;
    if (!s->dsp_motion_functional_model || d->channel != 1 || written != 0xf ||
            words[3] > 1 || m->scheduled || m->ready || m->rx ||
            d->init_scheduled || d->init_ready || d->rx_is_init || !d->init_configured) { return false; }
    unsigned config_bytes = words[0] == 0x1a ? 0xd0 : 0x80;
    unsigned result_bytes = words[0] == 0x1a ? WL_MOTION_RESULT_BYTES : 4;
    uint64_t config, result, source, workspace;
    uint8_t data[0xd0];
    m->reject = 2;
    if ((words[0] != 0x1a && words[0] != 0x1b) ||
            !dsp_session_ram_address(s, 1, words[1], config_bytes, &config) ||
            !dsp_session_ram_address(s, 1, words[2], result_bytes, &result) ||
            address_space_read(&address_space_memory, config, MEMTXATTRS_UNSPECIFIED,
                data, config_bytes) != MEMTX_OK) { return false; }
    unsigned width = ldl_le_p(data + 8), height = ldl_le_p(data + 12), stride = ldl_le_p(data + 16);
    uint64_t image_bytes = (uint64_t)stride * height;
    m->reject = 3;
    if (width < 16 || height < 16 || width > 4096 || height > 4096 ||
            stride < width || stride > 8192 || image_bytes > 8 * MiB ||
            ldl_le_p(data + 0x14) || ldq_le_p(data) > UINT32_MAX ||
            ldq_le_p(data + 0x18) > UINT32_MAX || ldq_le_p(data + 0x20) != WL_DSP_SESSION_WORKSPACE_BYTES) {
        return false;
    }
    m->reject = 4;
    if (!dsp_session_ram_address(s, 1, ldq_le_p(data), image_bytes, &source) ||
            !dsp_session_ram_address(s, 1, ldq_le_p(data + 0x18), WL_DSP_SESSION_WORKSPACE_BYTES, &workspace) ||
            workspace != d->init_workspace) { return false; }
    uint64_t addresses[] = {config, source, workspace, result};
    uint32_t sizes[] = {config_bytes, image_bytes, WL_DSP_SESSION_WORKSPACE_BYTES, result_bytes};
    m->reject = 5;
    for (unsigned i = 0; i < 4; i++) {
        for (unsigned j = i + 1; j < 4; j++) {
            if (dsp_session_overlap(addresses[i], sizes[i], addresses[j], sizes[j])) { return false; }
        }
    }
    m->reject = 6;
    uint8_t *input = g_malloc(image_bytes);
    if (address_space_read(&address_space_memory, source, MEMTXATTRS_UNSPECIFIED,
            input, image_bytes) != MEMTX_OK) { g_free(input); return false; }
    m->input = input; m->input_crc = crc32(0, input, image_bytes);
    m->config = config; m->source = source; m->result = result; m->workspace = workspace;
    m->width = width; m->height = height; m->stride = stride;
    m->input_bytes = image_bytes; m->result_bytes = result_bytes;
    m->opcode = words[0]; m->group = words[3]; m->reject = 0;
    m->requests++; m->scheduled = true;
    /* Functional host job deadline, independent of CEVA instruction/pause
     * timing. TX confirmation remains transport, never numerical completion. */
    timer_mod(m->timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + WL_DSP_BOOT_DELAY_NS);
    return true;
}
static bool dsp_moving_submit(NikonZ8State *s, WlDspBootChannel *d,
                              const uint32_t *words, uint32_t written)
{
    WlMotionJob *m = &d->motion;
    WlMovingWork work = {0};
    uint8_t input[0x50], output[0xd0];
    uint64_t config, result;
    static const unsigned bpp[8] = {1, 1, 4, 2, 2, 2, 2, 2};
    m->reject = 18;
    if (!s->dsp_motion_functional_model || d->channel != 1 || written != 15 ||
            words[0] != 0x18 || words[3] > 1 || m->scheduled || m->ready || m->rx ||
            d->init_scheduled || d->init_ready || d->rx_is_init ||
            !dsp_session_ram_address(s, 1, words[1], sizeof(input), &config) ||
            !dsp_session_ram_address(s, 1, words[2], sizeof(output), &result) ||
            address_space_read(&address_space_memory, config, MEMTXATTRS_UNSPECIFIED,
                input, sizeof(input)) != MEMTX_OK ||
            address_space_read(&address_space_memory, result, MEMTXATTRS_UNSPECIFIED,
                output, sizeof(output)) != MEMTX_OK) { return false; }
    m->reject = 19;
    work.center_x = ldl_le_p(input + 0x30); work.center_y = ldl_le_p(input + 0x34);
    work.workspace_bytes = ldl_le_p(input + 0x40);
    work.hint_x = (int16_t)lduw_le_p(input + 0x44);
    work.hint_y = (int16_t)lduw_le_p(input + 0x46);
    work.threshold = lduw_le_p(input + 0x48);
    if (work.center_x < 64 || work.center_y < 64 ||
            abs(work.hint_x) > 32 || abs(work.hint_y) > 32 ||
            !work.threshold || work.threshold > 255 ||
            lduw_le_p(input + 0x4a) || lduw_le_p(input + 0x4c) ||
            lduw_le_p(input + 0x4e) > 2 || work.workspace_bytes != 0x100000 ||
            ldq_le_p(input + 0x38) > UINT32_MAX ||
            !dsp_session_ram_address(s, 1, ldq_le_p(input + 0x38),
                work.workspace_bytes, &work.workspace)) { return false; }
    uint64_t addresses[13] = {config, result, work.workspace};
    uint32_t lengths[13] = {sizeof(input), sizeof(output), work.workspace_bytes};
    for (unsigned image = 0; image < 2; image++) {
        const uint8_t *p = input + image * 0x18;
        unsigned width = ldl_le_p(p + 8), height = ldl_le_p(p + 12), stride = ldl_le_p(p + 16);
        m->reject = 20;
        if (ldq_le_p(p) > UINT32_MAX || ldl_le_p(p + 20) ||
                width > 4096 || height > 4096 || width < 128 || height < 128 ||
                stride < width || stride > 8192 ||
                work.center_x > width - 64 || work.center_y > height - 64 ||
                (uint64_t)stride * height > 8 * MiB ||
                !dsp_session_ram_address(s, 1, ldq_le_p(p), stride * height,
                    &work.sources[image])) { return false; }
        work.widths[image] = width; work.heights[image] = height; work.strides[image] = stride;
        addresses[3 + image] = work.sources[image]; lengths[3 + image] = stride * height;
    }
    for (unsigned plane = 0; plane < 8; plane++) {
        const uint8_t *p = output + plane * 0x18;
        unsigned pitch = ldl_le_p(p + 16);
        m->reject = 21;
        if (ldq_le_p(p) > UINT32_MAX || ldl_le_p(p + 8) != 32 || ldl_le_p(p + 12) != 32 ||
                ldl_le_p(p + 20) || pitch < 32 * bpp[plane] || pitch > 512 ||
                !dsp_session_ram_address(s, 1, ldq_le_p(p), pitch * 32,
                    &work.destinations[plane])) { return false; }
        work.pitches[plane] = pitch;
        addresses[5 + plane] = work.destinations[plane]; lengths[5 + plane] = pitch * 32;
    }
    m->reject = 22;
    for (unsigned i = 0; i < 13; i++) {
        for (unsigned j = i + 1; j < 13; j++) {
            /* Two read-only input images may intentionally share storage. */
            if (i == 3 && j == 4) { continue; }
            if (dsp_session_overlap(addresses[i], lengths[i], addresses[j], lengths[j])) { return false; }
        }
    }
    m->reject = 23;
    uint32_t checksum = 0;
    for (unsigned image = 0; image < 2; image++) {
        work.input[image] = g_malloc(lengths[3 + image]);
        if (address_space_read(&address_space_memory, work.sources[image], MEMTXATTRS_UNSPECIFIED,
                work.input[image], lengths[3 + image]) != MEMTX_OK) {
            g_free(work.input[0]); g_free(work.input[1]); return false;
        }
        checksum = crc32(checksum, work.input[image], lengths[3 + image]);
    }
    m->moving = work; m->config = config; m->result = result; m->workspace = work.workspace;
    m->source = work.sources[0]; m->width = work.widths[0]; m->height = work.heights[0];
    m->stride = work.strides[0]; m->input_bytes = lengths[3] + lengths[4]; m->result_bytes = 0xd0;
    m->input_crc = checksum; m->opcode = words[0]; m->group = words[3]; m->reject = 0;
    m->requests++; m->scheduled = true;
    timer_mod(m->timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + WL_DSP_BOOT_DELAY_NS);
    return true;
}
static bool dsp_session_program_address(NikonZ8State *s, unsigned channel,
                                        uint32_t local, uint32_t bytes, uint64_t *physical)
{
    /* Even low local addresses refer to the configured DSP RAM aperture.
     * Consume the actual caller-provided RAM bytes, not a similarly numbered
     * span in the low firmware ROM image. Native program RAM may differ. */
    return dsp_session_ram_address(s, channel, local, bytes, physical);
}
static void dsp_session_program_free(WlDspBootChannel *d)
{
    for (unsigned i = 0; i < 2; i++) {
        g_free(d->init_program[i]); d->init_program[i] = NULL;
        d->init_program_bytes[i] = d->init_crc[i] = 0;
    }
}
/* Functional LPCM backend. Declared left-aligned LE signed PCM,
 * byte truncation/zero extension; original core ISA/rounding unverified. */
static bool lpcm_address(NikonZ8State *s, unsigned direction,
                                  uint32_t local, uint32_t bytes, uint64_t *physical)
{
    if (!s->bus_window_fixture || !bytes) { return false; }
    for (unsigned entry=direction*2;entry<32;entry+=4) {
        unsigned bank=!!(s->bus_windows[10][0][entry][0]&0x10);
        uint64_t *w=s->bus_windows[10][bank][entry];
        uint32_t start=w[0]&0xffffffc0,span=-(uint32_t)(w[1]&0xffffffc0);
        if (local>=start && (uint64_t)local-start<span && bytes<=span-((uint64_t)local-start)) {
            *physical=(((bank?UINT64_C(0x800000000):UINT64_C(0xc00000000))+
                (w[2]&UINT64_C(0xfffffffc0)))&UINT64_C(0xfffffffc0))+local-start;
            if (s->lpcm_ram_aperture_fixture && entry<4 && w[2]==0 &&
                w[1]==(UINT64_C(1)<<36)-MACHINE(s)->ram_size) {
                *physical=UINT64_C(0xa00000000)+local-start;
            }
            return dma_ram_range(s,*physical,bytes);
        }
    }
    return false;
}
static bool lpcm_submit(NikonZ8State *s,WlDspBootChannel *d,
                                const uint32_t *w,uint32_t mask)
{
    if (mask!=0x1ff || w[0]!=2 || d->init_ready || d->rx_pending) { return false; }
    unsigned used=w[1]==1?5:w[1]==2?2:w[1]==3?4:9;
    if (used==9) { return false; }
    for (unsigned i=used;i<9;i++) { if(w[i]) { return false; } }
    uint64_t src,dst;
    if (w[1]==1) {
        if (d->init_configured || w[2]<1 || w[2]>4 ||
            !lpcm_address(s,0,w[3],0x2f000,&src) ||
            !lpcm_address(s,1,w[4],0x2f000,&dst) ||
            (src<dst+0x2f000 && dst<src+0x2f000)) { return false; }
        d->lpcm_mode=w[2];d->lpcm_input=w[3];d->lpcm_output=w[4];d->init_configured=true;
    } else if (w[1]==2) {
        if (!d->init_configured) { return false; }
        d->init_configured=false;
    } else {
        unsigned ib=d->lpcm_mode==1 || d->lpcm_mode==3?4:3;
        unsigned ob=d->lpcm_mode==1?3:d->lpcm_mode==2?4:2;
        if (!d->init_configured || !w[2] || w[2]>0x2f000 || w[2]%ib ||
            w[3]!=w[2]/ib*ob || w[3]>0x2f000 ||
            !lpcm_address(s,0,d->lpcm_input,w[2],&src) ||
            !lpcm_address(s,1,d->lpcm_output,w[3],&dst) ||
            (src<dst+w[3] && dst<src+w[2])) { return false; }
        uint8_t *input=g_malloc(w[2]),*output=g_malloc0(w[3]);
        bool ok=address_space_read(&address_space_memory,src,MEMTXATTRS_UNSPECIFIED,input,w[2])==MEMTX_OK;
        if (ok) {
            for (unsigned i=0,j=0;i<w[2];i+=ib,j+=ob) {
                if (ob<ib) { memcpy(output+j,input+i+ib-ob,ob); }
                else { memcpy(output+j+ob-ib,input+i,ib); }
            }
            ok=address_space_write(&address_space_memory,dst,MEMTXATTRS_UNSPECIFIED,output,w[3])==MEMTX_OK;
        }
        g_free(input);g_free(output);
        if (!ok) { return false; }
        d->lpcm_jobs++;d->lpcm_input_bytes+=w[2];d->lpcm_output_bytes+=w[3];
    }
    memset(d->lpcm_reply,0,sizeof(d->lpcm_reply));d->lpcm_reply[0]=2;d->lpcm_reply[1]=w[1];
    if(w[1]==3) { d->lpcm_reply[2]=w[2]; }
    d->init_ready=true;d->init_completed++;
    fprintf(stderr,"Z8_LPCM_JOB command=%u mode=%u words=%08x,%08x,%08x,%08x,%08x jobs=%"PRIu64"\n",w[1],d->lpcm_mode,w[0],w[1],w[2],w[3],w[4],d->lpcm_jobs);
    return true;
}

static void dsp_session_try_reply(WlDspBootChannel *d)
{
    if (!d->init_ready || d->reset_held || d->rx_pending || d->tx_scheduled ||
            d->tx_pending || d->claims[d->tx_slot] || d->claims[0]) { return; }
    memset(d->rx, 0, sizeof(d->rx));
    d->rx[0] = d->init_opcode;
    d->rx[1] = 0; /* This backend's actual initialized-session result. */
    d->rx[2] = d->init_group;
    if (d->channel==3) { memcpy(d->rx,d->lpcm_reply,sizeof(d->lpcm_reply)); }
    d->rx_pending = d->rx_is_init = true;
    d->init_ready = false;
    d->init_replies++;
    if (d->init_is_correction) { d->correction.rx = true; d->correction.replies++; }
    dsp_boot_irq_update(d);
}
static void dsp_session_initialize(void *opaque)
{
    WlDspBootChannel *d = opaque;
    if (!d->init_scheduled || d->reset_held) { return; }
    if (d->init_is_correction) { correction_initialize(&d->correction); }
    /* Only the validated, owned initialization workspace is cleared. This
     * is a declared functional assumption, not reconstructed vendor code. */
    const uint8_t zeros[4096] = {0};
    uint32_t written = 0;
    while (written < d->init_workspace_bytes) {
        uint32_t amount = MIN((uint32_t)sizeof(zeros), d->init_workspace_bytes - written);
        if (address_space_write(&address_space_memory, d->init_workspace + written,
                MEMTXATTRS_UNSPECIFIED, zeros, amount) != MEMTX_OK) {
            d->init_scheduled = false;
            unknown_access(d->owner, wl_dsp_mailboxes[d->channel] + 0x108, 1, 4, true);
            return;
        }
        written += amount;
    }
    d->init_scheduled = false;
    d->init_configured = d->init_ready = true;
    d->init_completed++;
    dsp_session_try_reply(d);
}
static bool dsp_session_submit(NikonZ8State *s, WlDspBootChannel *d,
                               const uint32_t *words, uint32_t written_mask)
{
    if (!s->dsp_session_init_model) { return true; }
    d->init_reject_code = 1;
    memcpy(d->init_debug_window, s->bus_windows[3 + d->channel][1][0], sizeof(d->init_debug_window));
    if (written_mask != 0xf || words[2] || words[3] > 1 || d->init_scheduled ||
            d->init_ready || d->rx_is_init || d->motion.scheduled || d->motion.ready || d->motion.rx) { return false; }
    uint64_t parameter = 0, workspace = 0, programs[2] = {0};
    uint32_t capacity = 0, lengths[2] = {0}, checksums[2] = {0};
    uint8_t *copies[2] = {NULL};
    if (d->channel == 1 && words[0] == 0x19) {
        d->init_reject_code = 2;
        capacity = WL_DSP_SESSION_WORKSPACE_BYTES;
        /* Z8 40fe6b2c / ZR411d6274 separate a44e00 DSP prefix from
         * the CPU-owned12040-byte tail in the56e40 allocation. */
        if (!dsp_session_ram_address(s, 1, words[1], WL_DSP_SESSION_ALLOCATION_BYTES, &workspace)) { return false; }
        parameter = workspace;
    } else if (d->channel == 2 && words[0] == 0x1d) {
        d->init_reject_code = 3;
        uint8_t header[0x48];
        if (!dsp_session_ram_address(s, 2, words[1], sizeof(header), &parameter) ||
                address_space_read(&address_space_memory, parameter, MEMTXATTRS_UNSPECIFIED,
                    header, sizeof(header)) != MEMTX_OK) { return false; }
        d->init_debug_parameter = parameter;
        for (unsigned i = 0; i < 9; i++) { d->init_debug_header[i] = ldq_le_p(header + i * 8); }
        d->init_reject_code = 4;
        if (ldl_le_p(header) != 0x10800 ||
                ldl_le_p(header + 4) || ldq_le_p(header + 0x28) || ldq_le_p(header + 0x30) ||
                ldl_le_p(header + 0x44) || ldl_le_p(header + 0x10 + 4) ||
                ldl_le_p(header + 0x20 + 4) || ldl_le_p(header + 0x40) != WL_DSP_MODULE_WORKSPACE_BYTES) {
            return false;
        }
        capacity = WL_DSP_MODULE_WORKSPACE_BYTES;
        d->init_reject_code = 5;
        uint64_t local_workspace = ldq_le_p(header + 0x38);
        if (local_workspace > UINT32_MAX ||
                !dsp_session_ram_address(s, 2, local_workspace, capacity, &workspace) ||
                dsp_session_overlap(parameter, sizeof(header), workspace, capacity)) { return false; }
        for (unsigned i = 0; i < 2; i++) {
            d->init_reject_code = 6;
            uint64_t local = ldq_le_p(header + 8 + i * 0x10);
            lengths[i] = ldl_le_p(header + 0x10 + i * 0x10);
            if (local > UINT32_MAX || !lengths[i] || lengths[i] > 16 * MiB ||
                    !dsp_session_program_address(s, 2, local, lengths[i], &programs[i]) ||
                    dsp_session_overlap(programs[i], lengths[i], workspace, capacity) ||
                    dsp_session_overlap(programs[i], lengths[i], parameter, sizeof(header))) {
                goto invalid;
            }
        }
        d->init_reject_code = 7;
        if (dsp_session_overlap(programs[0], lengths[0], programs[1], lengths[1])) { goto invalid; }
        for (unsigned i = 0; i < 2; i++) {
            d->init_reject_code = 8 + i;
            copies[i] = g_malloc(lengths[i]);
            if (address_space_read(&address_space_memory, programs[i], MEMTXATTRS_UNSPECIFIED,
                    copies[i], lengths[i]) != MEMTX_OK) { goto invalid; }
            bool nonzero = false;
            for (uint32_t k = 0; k < lengths[i]; k++) { nonzero |= copies[i][k] != 0; }
            d->init_reject_code = 10 + i;
            if (!nonzero) { goto invalid; }
            checksums[i] = crc32(0, copies[i], lengths[i]);
        }
    } else { d->init_reject_code = 12; return false; }
    d->init_reject_code = 0;
    d->init_is_correction = false;
    if (d->channel == 1 && words[0] == 0x19) { motion_job_reset(&d->motion); }
    dsp_session_program_free(d);
    for (unsigned i = 0; i < 2; i++) {
        d->init_program[i] = copies[i]; d->init_program_bytes[i] = lengths[i]; d->init_crc[i] = checksums[i];
    }
    d->init_parameter = parameter;
    d->init_workspace = workspace;
    d->init_workspace_bytes = capacity;
    d->init_opcode = words[0]; d->init_group = words[3];
    d->init_configured = false;
    d->init_requests++;
    d->init_scheduled = true;
    timer_mod(d->init_timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + WL_DSP_BOOT_DELAY_NS);
    return true;
invalid:
    g_free(copies[0]); g_free(copies[1]);
    return false;
}
static void dsp_boot_tx_complete(void *opaque)
{
    WlDspBootChannel *d = opaque;
    if (!d->tx_scheduled || d->reset_held) { return; }
    d->tx_scheduled = false;
    d->tx_pending = true;
    d->tx_confirmations++;
    /* Message transport only. No job result, RX packet, pixel write or
     * original DSP execution is generated from an outgoing command. */
    dsp_boot_irq_update(d);
}
static void dsp_boot_complete(void *opaque)
{
    WlDspBootChannel *d = opaque;
    if (!d->scheduled || d->reset_held) { return; }
    d->scheduled = false;
    d->booted = true;
    /* Functional allocation: receive slot0, descriptor100 at port1 +84.
     * Allocation and the1ms delay are assumptions, not silicon measurements. */
    memset(d->rx, 0, sizeof(d->rx));
    d->rx[0] = UINT32_MAX;
    d->rx_is_init = false;
    d->rx_pending = true;
    d->replies++;
    dsp_boot_irq_update(d);
}
static bool dsp_boot_program_present(NikonZ8State *s, unsigned channel)
{
    unsigned index = channel * 2 + 1;
    const uint8_t *program = memory_region_get_ram_ptr(&s->dsp_load_ram[index]);
    /* Empty-upload guard only. Vendor instructions are not executed. */
    for (unsigned i = 0; i < dsp_load_ram[index].bytes; i++) {
        if (program[i]) { return true; }
    }
    return false;
}
static bool dsp_boot_csr_write(NikonZ8State *s, hwaddr addr,
                               uint64_t value, unsigned size)
{
    if (!s->dsp_boot_mailbox_model) { return false; }
    for (unsigned channel = 0; channel < 3; channel++) {
        if (addr != wl_dsp_csrs[channel] + 0x28) { continue; }
        if (size != 4 || value > 1) { goto invalid; }
        WlDspBootChannel *d = &s->dsp_boot->channels[channel];
        if (value) {
            motion_job_reset(&d->motion);
            correction_reset(&d->correction);
            d->init_is_correction = false;
            if (d->init_scheduled || d->init_ready || d->rx_is_init) { d->init_cancelled++; }
            timer_del(d->init_timer);
            d->init_scheduled = d->init_ready = d->init_configured = d->rx_is_init = false;
            dsp_session_program_free(d);
            if (d->scheduled) { d->cancelled++; }
            timer_del(d->timer);
            if (d->tx_scheduled) { d->tx_cancelled++; }
            timer_del(d->tx_timer);
            d->tx_scheduled = d->tx_pending = false;
            d->scheduled = false;
            d->reset_held = true;
            d->booted = d->rx_pending = false;
            d->core_control = 0;
            memset(d->rx, 0, sizeof(d->rx));
            dsp_boot_irq_update(d);
        } else if (d->reset_held) {
            uint32_t *csr = s->dsp_init[channel];
            if (csr[0x24 / 4] != 1 || csr[0] || csr[0x20 / 4] || csr[0x40 / 4] ||
                    !dsp_boot_program_present(s, channel)) { goto invalid; }
            d->reset_held = false;
            d->scheduled = true;
            d->requests++;
            timer_mod(d->timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + WL_DSP_BOOT_DELAY_NS);
        }
        s->dsp_init[channel][0x28 / 4] = value;
        return true;
    }
    return false;
invalid:
    unknown_access(s, addr, value, size, true);
    return true;
}
static bool dsp_boot_status_access(NikonZ8State *s, hwaddr addr,
                                  uint64_t *value, unsigned size, bool write)
{
    if (!s->dsp_boot_mailbox_model) { return false; }
    for (unsigned channel = 0; channel < 3; channel++) {
        hwaddr base = wl_dsp_csrs[channel];
        WlDspBootChannel *d = &s->dsp_boot->channels[channel];
        if (addr == base + 0x54) {
            if (write || size != 4) { goto invalid; }
            /* Original40e0aac4/40c0a664: powered/resumed status3,
             * pause request bit0 waits for status2; bit8 requests status0.
             * These are functional control states, not DSP instruction proof. */
            *value = !d->booted || d->reset_held || (d->core_control & 0x100) ? 0 :
                     d->core_control & 1 ? 8 : 12;
            return true;
        }
        if (addr == base + 0x52 && !write && size == 2) {
            *value = d->core_control >> 16; return true;
        }
        if (addr == base + 0x50) {
            if (write) {
                if (size != 4 || *value & ~UINT64_C(0x101)) { goto invalid; }
                d->core_control = *value;
            } else {
                if (size != 2 && size != 4) { goto invalid; }
                *value = d->core_control;
            }
            return true;
        }
    }
    return false;
invalid:
    unknown_access(s, addr, *value, size, write);
    if (!write) { *value = 0; }
    return true;
}
static bool dsp_boot_mailbox_access(NikonZ8State *s, hwaddr addr,
                                    uint64_t *value, unsigned size, bool write)
{
    if (!s->dsp_boot_mailbox_model && !s->lpcm_host_conversion_model) { return false; }
    for (unsigned channel = 0; channel < 4; channel++) {
        if ((channel==3 && !s->lpcm_host_conversion_model) || (channel<3 && !s->dsp_boot_mailbox_model)) { continue; }
        hwaddr base = wl_dsp_mailboxes[channel];
        if (addr < base || addr >= base + 0x904) { continue; }
        WlDspBootChannel *d = &s->dsp_boot->channels[channel];
        unsigned off = addr - base;
        if (size != 4 || (addr & 3) || (write && *value > UINT32_MAX)) { goto invalid; }
        if (off == 0x84 && !write) { *value = d->rx_pending ? 0x100 : 0; return true; }
        if (off == 0x80 && !write) {
            *value = d->tx_pending ? 0x100 + d->tx_slot * 0x80 : 0; return true;
        }
        if (off >= 0x80 && off < 0xa0 && !write) { *value = 0; return true; }
        if (off == 0x900 && !write) {
            uint32_t busy = d->rx_pending ? 1 : 0;
            for (unsigned i = 0; i < 8; i++) {
                if (d->claims[i]) { busy |= 1U << i; }
            }
            *value = busy; return true;
        }
        if (off < 0x100 || off >= 0x500) { goto invalid; }
        unsigned slot = (off - 0x100) / 0x80;
        unsigned reg = (off - 0x100) % 0x80;
        if (reg >= 0x40) {
            unsigned word = (reg - 0x40) / 4;
            if (write) {
                if (slot == 0 && d->rx_pending) { goto invalid; }
                d->tx[slot][word] = *value;
                d->tx_written[slot] |= 1U << word;
            } else { *value = slot == 0 && d->rx_pending ? d->rx[word] : d->tx[slot][word]; }
            return true;
        }
        if (!write) {
            switch (reg) {
            case 0x00: *value = d->claims[slot]; break;
            case 0x04: *value = d->lengths[slot]; break;
            case 0x10: *value = d->destinations[slot]; break;
            case 0x38:
                *value = d->tx_pending && slot == d->tx_slot ? d->destinations[slot] : 0;
                break;
            default: goto invalid;
            }
            return true;
        }
        switch (reg) {
        case 0x00:
            if (*value > UINT16_MAX || (slot == 0 && d->rx_pending) ||
                (slot == d->tx_slot && (d->tx_scheduled || d->tx_pending))) { goto invalid; }
            if (*value && !d->claims[slot]) {
                memset(d->tx[slot], 0, sizeof(d->tx[slot])); d->tx_written[slot] = 0;
            }
            d->claims[slot] = *value; break;
        case 0x04:
            if (*value > 7) { goto invalid; }
            d->lengths[slot] = *value; break;
        case 0x10:
            if (*value > UINT16_MAX) { goto invalid; }
            d->destinations[slot] = *value; break;
        case 0x14:
            if (*value != 0 && *value != 2) { goto invalid; }
            if (slot == 0 && *value == 2 && d->rx_pending) {
                d->rx_pending = false;
                if (d->motion.rx) { d->motion.acks++; d->motion.rx = false; }
                else if (d->rx_is_init) {
                    d->init_acks++;
                    if (d->init_is_correction && d->correction.rx) {
                        d->correction.rx = false; d->correction.acks++;
                    }
                } else { d->acknowledgements++; }
                d->rx_is_init = false;
            }
            break;
        case 0x34:
            if (*value & ~UINT64_C(0xffff)) { goto invalid; }
            if (d->tx_pending && slot == d->tx_slot && (*value & d->destinations[slot])) {
                d->tx_pending = false; d->tx_acks++;
            }
            break;
        case 0x08:
            if (*value != 1 || !d->booted || d->reset_held ||
                d->tx_scheduled || d->tx_pending || !d->claims[slot] ||
                d->lengths[slot] != 3 || d->destinations[slot] != 0x10 ||
                !d->tx_written[slot] || (d->tx_written[slot] & (d->tx_written[slot] + 1))) {
                goto invalid;
            }
            if (d->channel==3) {
                if (!lpcm_submit(s,d,d->tx[slot],d->tx_written[slot])) { d->lpcm_rejects++; goto invalid; }
            } else if (s->dsp_motion_functional_model && d->channel == 1 && d->tx[slot][0] == 0x18) {
                if (!dsp_moving_submit(s, d, d->tx[slot], d->tx_written[slot])) { goto invalid; }
            } else if (s->dsp_motion_functional_model && d->channel == 1 &&
                    (d->tx[slot][0] == 0x1a || d->tx[slot][0] == 0x1b)) {
                if (!dsp_motion_submit(s, d, d->tx[slot], d->tx_written[slot])) { goto invalid; }
            } else if (s->dsp_correction_init_model && !d->channel &&
                    (d->tx[slot][0] == 0 || d->tx[slot][0] == 1)) {
                if (!dsp_correction_submit(s, d, d->tx[slot], d->tx_written[slot])) { goto invalid; }
            } else if (!dsp_session_submit(s, d, d->tx[slot], d->tx_written[slot])) { goto invalid; }
            d->tx_slot = slot;
            memcpy(d->last_tx, d->tx[slot], sizeof(d->last_tx));
            d->last_tx_written = d->tx_written[slot];
            d->last_tx_control = d->core_control;
            d->last_tx_claim = d->claims[slot];
            d->last_tx_route = d->lengths[slot];
            d->last_tx_destination = d->destinations[slot];
            d->tx_requests++;
            d->tx_scheduled = true;
            timer_mod(d->tx_timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + WL_DSP_BOOT_DELAY_NS);
            break;
        default:
            /* Outgoing processing and unproved notifications/mask registers
             * need their own contract. Never turn them into successful jobs. */
            goto invalid;
        }
        dsp_session_try_reply(d);
        dsp_motion_try_reply(d);
        dsp_boot_irq_update(d);
        return true;
    }
    return false;
invalid:
    unknown_access(s, addr, *value, size, write);
    if (!write) { *value = 0; }
    return true;
}
static void dsp_boot_init(NikonZ8State *s, DeviceState *gic)
{
    if (!s->dsp_boot_mailbox_model && !s->lpcm_host_conversion_model) { return; }
    if (!s->bootstrap_fixtures) {
        error_report("DSP boot mailbox requires bootstrap-fixtures=on"); exit(1);
    }
    if (s->dsp_session_init_model && !s->dsp_ram_aperture_fixture) {
        error_report("dsp-session-init-model requires explicit DSP RAM aperture input"); exit(1);
    }
    s->dsp_boot = g_new0(WlDspBootState, 1);
    for (unsigned i = 0; i < 4; i++) {
        WlDspBootChannel *d = &s->dsp_boot->channels[i];
        d->owner = s; d->channel = i;
        d->irq = qdev_get_gpio_in(gic, wl_dsp_rx_irqs[i] - 32);
        d->tx_irq = qdev_get_gpio_in(gic, wl_dsp_rx_irqs[i] - 1 - 32);
        d->timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, dsp_boot_complete, d);
        d->tx_timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, dsp_boot_tx_complete, d);
        d->init_timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, dsp_session_initialize, d);
        d->motion.timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, dsp_motion_complete, d);
    }
}
static bool get_dsp_boot_mailbox_model(Object *obj, Error **errp)
{ return NIKON_Z8_LAB(obj)->dsp_boot_mailbox_model; }
static void set_dsp_boot_mailbox_model(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    if (s->image_ram.ram || s->image_ram.rom_device) {
        error_setg(errp, "DSP mailbox mode is immutable after realization"); return;
    }
    s->dsp_boot_mailbox_model = value;
}
static bool get_dsp_session_init_model(Object *obj, Error **errp)
{ return NIKON_Z8_LAB(obj)->dsp_session_init_model; }
static void set_dsp_session_init_model(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    if (s->image_ram.ram || s->image_ram.rom_device) {
        error_setg(errp, "DSP session model is immutable after realization"); return;
    }
    s->dsp_session_init_model = value;
}
static bool get_dsp_motion_functional_model(Object *obj, Error **errp)
{ return NIKON_Z8_LAB(obj)->dsp_motion_functional_model; }
static void set_dsp_motion_functional_model(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    if (s->image_ram.ram || s->image_ram.rom_device) {
        error_setg(errp, "DSP functional motion mode is immutable after realization"); return;
    }
    s->dsp_motion_functional_model = value;
}
static char *get_dsp_motion_state(Object *obj, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    WlMotionJob zero = {0}, *m = s->dsp_boot ? &s->dsp_boot->channels[1].motion : &zero;
    return g_strdup_printf("{\"enabled\":%s,\"scheduled\":%s,\"ready\":%s,\"rx_pending\":%s,"
        "\"requests\":%" PRIu64 ",\"completed\":%" PRIu64 ",\"replies\":%" PRIu64
        ",\"acks\":%" PRIu64 ",\"cancelled\":%" PRIu64 ",\"bytes_read\":%" PRIu64
        ",\"bytes_written\":%" PRIu64 ",\"opcode\":%u,\"group\":%u,\"width\":%u,\"height\":%u,\"stride\":%u,"
        "\"source\":%" PRIu64 ",\"result\":%" PRIu64 ",\"input_bytes\":%u,\"result_bytes\":%u,"
        "\"input_crc32\":%u,\"result_crc32\":%u,\"new_features\":%u,\"tracks\":%u,\"inliers\":%u,"
        "\"dx\":%d,\"dy\":%d,\"reject\":%u,\"group_point_counts\":[%u,%u],"
        "\"original_dsp_execution\":false,\"scope\":\"explicit functional FAST9/SAD translation and message results; original CEVA, KRAN scores/classification/age and physical timing unproved\"}",
        s->dsp_motion_functional_model ? "true" : "false", m->scheduled ? "true" : "false",
        m->ready ? "true" : "false", m->rx ? "true" : "false",
        m->requests, m->completed, m->replies, m->acks, m->cancelled, m->bytes_read, m->bytes_written,
        m->opcode, m->group, m->width, m->height, m->stride, m->source, m->result,
        m->input_bytes, m->result_bytes, m->input_crc, m->result_crc, m->features, m->tracks,
        m->inliers, m->dx, m->dy, m->reject, m->history[0].count, m->history[1].count);
}
static bool get_dsp_correction_init_model(Object *obj, Error **errp)
{ return NIKON_Z8_LAB(obj)->dsp_correction_init_model; }
static void set_dsp_correction_init_model(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    if (s->image_ram.ram || s->image_ram.rom_device) {
        error_setg(errp, "DSP correction initialization is immutable after realization"); return;
    }
    s->dsp_correction_init_model = value;
}
static char *get_dsp_correction_state(Object *obj, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    WlCorrectionWork zero = {0}, *c = s->dsp_boot ? &s->dsp_boot->channels[0].correction : &zero;
    GString *out = g_string_new(NULL);
    g_string_append_printf(out, "{\"enabled\":%s,\"queued\":%s,\"configured\":%s,\"rx_pending\":%s,"
        "\"requests\":%" PRIu64 ",\"completed\":%" PRIu64 ",\"replies\":%" PRIu64
        ",\"acks\":%" PRIu64 ",\"cancelled\":%" PRIu64 ",\"address_resets\":%" PRIu64
        ",\"opcode\":%u,\"reject\":%u,\"calibration_count\":%u,\"parameter\":%" PRIu64
        ",\"calibration\":%" PRIu64 ",\"width\":%u,\"height\":%u,\"stride\":%u,\"frame_bytes\":%u,"
        "\"parameter_crc32\":%u,\"calibration_crc32\":%u,\"context_crc32\":%u,"
        "\"parameter_bytes_read\":%" PRIu64 ",\"calibration_bytes_read\":%" PRIu64
        ",\"internal_bytes_written\":%" PRIu64 ",\"plan_count\":%u,\"plan_crc32\":%u,\"parameter_hex\":\"",
        s->dsp_correction_init_model ? "true" : "false", c->queued ? "true" : "false",
        c->configured ? "true" : "false", c->rx ? "true" : "false",
        c->requests, c->completed, c->replies, c->acks, c->cancelled, c->resets,
        c->opcode, c->reject, c->raw_count, c->parameter, c->calibration,
        c->width, c->height, c->stride, c->frame_bytes, c->parameter_crc, c->calibration_crc,
        c->context_crc, c->parameter_bytes_read, c->calibration_bytes_read, c->internal_bytes_written,
        c->plan_count, c->plan_crc);
    for (unsigned i = 0; i < sizeof(c->parameters); i++) { g_string_append_printf(out, "%02x", c->parameters[i]); }
    g_string_append(out, "\",\"calibration_hex\":\"");
    for (unsigned i = 0; i < sizeof(c->payload); i++) { g_string_append_printf(out, "%02x", c->payload[i]); }
    g_string_append(out, "\",\"context_hex\":\"");
    for (unsigned i = 0; i < sizeof(c->context); i++) { g_string_append_printf(out, "%02x", c->context[i]); }
    g_string_append(out, "\",\"plan_hex\":\"");
    for (unsigned i = 0; i < sizeof(c->plan); i++) {
        g_string_append_printf(out, "%02x", ((const uint8_t *)c->plan)[i]);
    }
    g_string_append(out, "\",\"original_dsp_execution\":false,\"pixels_produced\":false,"
        "\"nonempty_calibration_supported\":true,\"original_correction_transform\":false,"
        "\"scope\":\"actual calibration/context and generic same-CFA neighbor plan; no original ISA, vendor transform or pixel processing\"}");
    return g_string_free(out, false);
}
static char *get_dsp_boot_mailbox_state(Object *obj, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    GString *out = g_string_new(NULL);
    g_string_append_printf(out, "{\"enabled\":%s,\"channels\":[", s->dsp_boot_mailbox_model ? "true" : "false");
    if (s->dsp_boot) {
        for (unsigned i = 0; i < 3; i++) {
            WlDspBootChannel *d = &s->dsp_boot->channels[i];
            g_string_append_printf(out, "%s{\"reset_held\":%s,\"scheduled\":%s,\"booted\":%s,"
                "\"requests\":%" PRIu64 ",\"replies\":%" PRIu64 ",\"acks\":%" PRIu64 ",\"cancelled\":%" PRIu64
                ",\"rx_pending\":%s,\"rx_irq\":%u,\"rx_slot\":0}", i ? "," : "", d->reset_held ? "true" : "false",
                d->scheduled ? "true" : "false", d->booted ? "true" : "false", d->requests, d->replies,
                d->acknowledgements, d->cancelled, d->rx_pending ? "true" : "false", wl_dsp_rx_irqs[i]);
            /* Append a bounded outgoing snapshot to this channel object. */
            g_string_truncate(out, out->len - 1);
            g_string_append_printf(out, ",\"tx_pending\":%s,\"tx_requests\":%" PRIu64
                ",\"tx_confirmations\":%" PRIu64 ",\"tx_acks\":%" PRIu64 ",\"tx_cancelled\":%" PRIu64
                ",\"last_tx_slot\":%u,\"last_tx_written\":%u,\"core_control\":%u,"
                "\"last_tx_control\":%u,\"last_tx_claim\":%u,\"last_tx_route\":%u,"
                "\"last_tx_destination\":%u,\"last_tx_words\":[",
                d->tx_pending ? "true" : "false", d->tx_requests, d->tx_confirmations, d->tx_acks,
                d->tx_cancelled, d->tx_slot, d->last_tx_written, d->core_control,
                d->last_tx_control, d->last_tx_claim, d->last_tx_route, d->last_tx_destination);
            for (unsigned word = 0; word < 16; word++) {
                g_string_append_printf(out, "%s%u", word ? "," : "", d->last_tx[word]);
            }
            g_string_append(out, "],\"tx_slots\":[");
            unsigned recorded_slots = 0;
            for (unsigned slot = 0; slot < 8; slot++) {
                if (!d->claims[slot] && !d->tx_written[slot]) { continue; }
                g_string_append_printf(out, "%s{\"slot\":%u,\"claim\":%u,\"route\":%u,"
                    "\"destination\":%u,\"written_mask\":%u,\"words\":[",
                    recorded_slots++ ? "," : "", slot, d->claims[slot], d->lengths[slot],
                    d->destinations[slot], d->tx_written[slot]);
                for (unsigned word = 0; word < 16; word++) {
                    g_string_append_printf(out, "%s%u", word ? "," : "", d->tx[slot][word]);
                }
                g_string_append(out, "]}");
            }
            g_string_append_printf(out, "],\"init_scheduled\":%s,\"init_ready\":%s,\"init_configured\":%s,"
                "\"rx_is_init\":%s,\"init_requests\":%" PRIu64 ",\"init_completed\":%" PRIu64
                ",\"init_replies\":%" PRIu64 ",\"init_acks\":%" PRIu64 ",\"init_cancelled\":%" PRIu64
                ",\"init_opcode\":%u,\"init_group\":%u,\"init_parameter\":%" PRIu64
                ",\"init_workspace\":%" PRIu64 ",\"init_workspace_bytes\":%u,"
                "\"program_bytes\":[%u,%u],\"program_crc32\":[%u,%u],\"init_reject_code\":%u,"
                "\"init_debug_parameter\":%" PRIu64 ",\"init_debug_window\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 "],"
                "\"init_debug_header\":[%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64
                ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 ",%" PRIu64 "]}",
                d->init_scheduled ? "true" : "false", d->init_ready ? "true" : "false",
                d->init_configured ? "true" : "false", d->rx_is_init ? "true" : "false",
                d->init_requests, d->init_completed, d->init_replies, d->init_acks, d->init_cancelled,
                d->init_opcode, d->init_group, d->init_parameter, d->init_workspace, d->init_workspace_bytes,
                d->init_program_bytes[0], d->init_program_bytes[1], d->init_crc[0], d->init_crc[1],
                d->init_reject_code, d->init_debug_parameter,
                d->init_debug_window[0], d->init_debug_window[1], d->init_debug_window[2],
                d->init_debug_header[0], d->init_debug_header[1], d->init_debug_header[2],
                d->init_debug_header[3], d->init_debug_header[4], d->init_debug_header[5],
                d->init_debug_header[6], d->init_debug_header[7], d->init_debug_header[8]);
        }
    }
    g_string_append_printf(out, "],\"dsp_arithmetic_executed\":false,\"boot_delay_ns\":1000000,"
        "\"session_initialization_enabled\":%s,\"processing_results_generated\":%s,"
        "\"motion_functional_enabled\":%s,"
        "\"scope\":\"functional boot/power/transport, optional initialization and FAST/SAD jobs; original DSP and inference unimplemented\"}",
        s->dsp_session_init_model ? "true" : "false",
        s->dsp_boot && s->dsp_boot->channels[1].motion.completed ? "true" : "false",
        s->dsp_motion_functional_model ? "true" : "false");
    return g_string_free(out, false);
}

static void lpcm_boot_ready(NikonZ8State *s)
{ if(s->dsp_boot) { s->dsp_boot->channels[3].booted=true;s->dsp_boot->channels[3].reset_held=false; } }
static void lpcm_reset(NikonZ8State *s)
{
 if(!s->dsp_boot) { return; }
 WlDspBootChannel *d=&s->dsp_boot->channels[3];
 timer_del(d->tx_timer);d->tx_scheduled=d->tx_pending=d->rx_pending=d->booted=d->init_configured=d->init_ready=d->rx_is_init=false;
 d->reset_held=true;memset(d->claims,0,sizeof(d->claims));dsp_boot_irq_update(d);
}

static char *get_lpcm_host_state(Object *obj, Error **errp)
{
    NikonZ8State *s=NIKON_Z8_LAB(obj);
    WlDspBootChannel empty={0};
    WlDspBootChannel *d=s->dsp_boot?&s->dsp_boot->channels[3]:&empty;
    return g_strdup_printf("{\"enabled\":%s,\"ram_aperture_fixture\":%s,\"boot_requests\":%"PRIu64
        ",\"boot_responses\":%"PRIu64",\"configured\":%s,\"mode\":%u,\"input_bus\":%u,\"output_bus\":%u,"
        "\"jobs\":%"PRIu64",\"input_bytes\":%"PRIu64",\"output_bytes\":%"PRIu64",\"rejects\":%"PRIu64
        ",\"tx_requests\":%"PRIu64",\"tx_acks\":%"PRIu64",\"rx_replies\":%"PRIu64",\"rx_acks\":%"PRIu64
        ",\"tx_pending\":%s,\"rx_pending\":%s,\"original_core_instructions_executed\":false,"
        "\"physical_packing_verified\":false,\"scope\":\"explicit left-aligned signed LE PCM width conversion; real RAM before IRQ; no audio source, file writer or decoder supplied\"}",
        s->lpcm_host_conversion_model?"true":"false",s->lpcm_ram_aperture_fixture?"true":"false",
        s->core1b_boot_requests,s->core1b_boot_responses,d->init_configured?"true":"false",
        d->lpcm_mode,d->lpcm_input,d->lpcm_output,d->lpcm_jobs,d->lpcm_input_bytes,
        d->lpcm_output_bytes,d->lpcm_rejects,d->tx_requests,d->tx_acks,d->init_replies,
        d->init_acks,d->tx_pending?"true":"false",d->rx_pending?"true":"false");
}

static void dsp_boot_finalize(NikonZ8State *s)
{
    if (!s->dsp_boot) { return; }
    for (unsigned i=0;i<WL_DSP_BOOT_CHANNELS;i++) {
        WlDspBootChannel *d=&s->dsp_boot->channels[i];
        motion_job_reset(&d->motion);
        dsp_session_program_free(d);
        if (d->timer) { timer_free(d->timer); }
        if (d->tx_timer) { timer_free(d->tx_timer); }
        if (d->init_timer) { timer_free(d->init_timer); }
        if (d->motion.timer) { timer_free(d->motion.timer); }
    }
    g_free(s->dsp_boot);
    s->dsp_boot=NULL;
}
