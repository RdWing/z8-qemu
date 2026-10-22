/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef WONDERLANTERN_HE_RUNTIME_H
#define WONDERLANTERN_HE_RUNTIME_H
#include <stddef.h>
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* Functional public-format codec. No claim of original Nikon arithmetic.
 * Buffers belong to the caller; failure never grants a device completion. */
int wl_he_encode14(const uint8_t *packed, size_t bytes, unsigned width,
                   unsigned height, unsigned pitch, uint8_t *output,
                   size_t capacity);
int wl_he_decode14(const uint8_t *packet, size_t bytes, unsigned width,
                   unsigned height, uint16_t *output, size_t samples);
#ifdef __cplusplus
}
#endif
#endif
