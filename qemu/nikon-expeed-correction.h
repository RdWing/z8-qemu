/* SPDX-License-Identifier: GPL-2.0-or-later
 * Functional calibration initialization and generic same-CFA neighbor plan.
 * Original instruction execution/vendor transforms remain unsupported.
 * Internal state is owned by this host model, never guest flags.
 */
#define WL_CPC_PARAMETER_BYTES 132
#define WL_CPC_CALIBRATION_BYTES 1504
#define WL_CPC_CONTEXT_BYTES 2304
typedef struct WlCorrectionPoint {
    uint16_t x, y;
    uint32_t row_offset, sample_index, cfa_phase, column_block, neighbor_count;
    uint32_t neighbors[4];
} WlCorrectionPoint;
typedef struct WlCorrectionWork {
    bool queued, configured, rx;
    uint32_t opcode, reject, raw_count, parameter_crc, calibration_crc, context_crc;
    uint64_t parameter, calibration;
    uint32_t width, height, stride, frame_bytes;
    uint8_t parameters[WL_CPC_PARAMETER_BYTES];
    uint8_t payload[WL_CPC_CALIBRATION_BYTES];
    uint8_t context[WL_CPC_CONTEXT_BYTES];
    WlCorrectionPoint plan[50];
    uint32_t plan_count, plan_crc;
    uint64_t requests, completed, replies, acks, cancelled, resets;
    uint64_t parameter_bytes_read, calibration_bytes_read, internal_bytes_written;
} WlCorrectionWork;

static void correction_reset(WlCorrectionWork *c)
{
    if (c->queued || c->rx) { c->cancelled++; }
    c->queued = c->configured = c->rx = false;
    memset(c->context, 0, sizeof(c->context));
    memset(c->plan, 0, sizeof(c->plan)); c->plan_count = 0;
    c->plan_crc = crc32(0, (const uint8_t *)c->plan, sizeof(c->plan));
    c->context_crc = crc32(0, c->context, sizeof(c->context));
}

static void correction_initialize(WlCorrectionWork *c)
{
    if (c->opcode == 1) {
        /* Both original reset functions ignore their two caller arguments.
         * CPC ResetAddress clears its owned address-generation word+1540. */
        stl_le_p(c->context + 1540, 0); c->resets++;
        c->internal_bytes_written += 4;
    } else {
        memset(c->context, 0, sizeof(c->context));
        memcpy(c->context, c->payload, sizeof(c->payload));
        memcpy(c->context + 1504, c->parameters + 88, 8);
        memcpy(c->context + 1512, c->parameters + 96, 4);
        memcpy(c->context + 1516, c->parameters + 128, 4);
        memcpy(c->context + 1520, c->parameters + 108, 4);
        memcpy(c->context + 1524, c->parameters + 56, 4);
        memcpy(c->context + 1528, c->parameters + 124, 4);
        /* Original packet has count16 followed by 50 records of30 bytes.
         * Preserve flags/coefficients in the packet. Our functional plan uses
         * only coordinates and same-CFA distance2 neighbors; it is not the
         * vendor's packed correction table or pixel arithmetic. */
        memset(c->plan, 0, sizeof(c->plan));
        c->plan_count = MIN(c->raw_count, 50);
        for (unsigned i = 0; i < c->plan_count; i++) {
            WlCorrectionPoint *point = &c->plan[i];
            point->x = lduw_le_p(c->payload + 2 + i * 30);
            point->y = lduw_le_p(c->payload + 4 + i * 30);
            point->row_offset = point->y * c->stride;
            point->sample_index = point->y * c->width + point->x;
            point->cfa_phase = (point->x & 1) | ((point->y & 1) << 1);
            point->column_block = point->x / 256;
            static const int dx[4] = {-2, 2, 0, 0}, dy[4] = {0, 0, -2, 2};
            for (unsigned k = 0; k < 4; k++) {
                int x = point->x + dx[k], y = point->y + dy[k];
                if (x >= 0 && y >= 0 && x < c->width && y < c->height) {
                    point->neighbors[point->neighbor_count++] = y * c->width + x;
                }
            }
        }
        c->plan_crc = crc32(0, (const uint8_t *)c->plan, sizeof(c->plan));
        /* Explicit functional stripe descriptors, not vendor packed DMA
         * words: source token, pitch, stripe rows and 256-column batch.
         * No DMA/frame or pixel result is created by initialization. */
        for (unsigned plane = 0; plane < 2; plane++) {
            unsigned offset = plane ? 1980 : 1548;
            stl_le_p(c->context + offset, ldl_le_p(c->parameters + 56));
            stl_le_p(c->context + offset + 4, c->stride);
            stl_le_p(c->context + offset + 8, plane ? 5 : 13);
            stl_le_p(c->context + offset + 12, 256);
        }
        c->configured = true;
        c->parameter_bytes_read += sizeof(c->parameters);
        c->calibration_bytes_read += sizeof(c->payload);
        c->internal_bytes_written += sizeof(c->context) + sizeof(c->plan);
    }
    c->context_crc = crc32(0, c->context, sizeof(c->context));
    c->queued = false; c->completed++;
}
