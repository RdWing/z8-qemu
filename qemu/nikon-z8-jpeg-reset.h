/* Copyright (C) 2026 RdWing: Z8 adaptation. */
/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Functional cancellation observed at C2.00 40C0D100..40C0D11C:
 * disarm both DMA controls, then reset an unfinished mode32 job.
 * A completed/pending IRQ must still be acknowledged by its original ISR. */
#ifndef HW_ARM_NIKON_Z8_JPEG_RESET_H
#define HW_ARM_NIKON_Z8_JPEG_RESET_H

#include <stdbool.h>
#include <stdint.h>

typedef enum Z8JPEGResetAction {
    Z8_JPEG_RESET_NONE,
    Z8_JPEG_RESET_DISARM,
    Z8_JPEG_RESET_CANCEL,
} Z8JPEGResetAction;

static Z8JPEGResetAction z8_jpeg_reset_action(const uint32_t *config,
        unsigned off, uint64_t value, unsigned size, bool requested,
        bool result_valid, uint32_t pending, uint32_t core)
{
    if (size != 4 || config[0] != 0x32 || !requested || result_valid ||
        pending || core) {
        return Z8_JPEG_RESET_NONE;
    }
    if ((off == 0x400 || off == 0x404) && value == 0) {
        return Z8_JPEG_RESET_DISARM;
    }
    if (off == 4 && value == 0x80000001 &&
        config[0x400 / 4] == 0 && config[0x404 / 4] == 0) {
        return Z8_JPEG_RESET_CANCEL;
    }
    return Z8_JPEG_RESET_NONE;
}

#endif
