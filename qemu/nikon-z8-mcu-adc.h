/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright (C) 2026 RdWing
 * Explicit external 12-bit ADC samples; no camera-specific control names.
 */
#ifndef NIKON_Z8_MCU_ADC_H
#define NIKON_Z8_MCU_ADC_H
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>

static bool z8_adc_decimal(const char **text, unsigned maximum, unsigned *value)
{
    const char *p = *text;
    unsigned n = 0;
    if (*p < '0' || *p > '9') { return false; }
    while (*p >= '0' && *p <= '9') {
        unsigned digit = *p++ - '0';
        if (n > maximum / 10 || (n == maximum / 10 && digit > maximum % 10)) { return false; }
        n = n * 10 + digit;
    }
    *text = p; *value = n; return true;
}

/* Validate the complete batch before changing any sample. */
static bool z8_adc_inputs(uint16_t values[3][19], const char *text)
{
    uint16_t next[3][19];
    bool seen[3][19] = { { false } };
    if (!text || !*text || strlen(text) > 1024) { return false; }
    memcpy(next, values, sizeof(next));
    for (;;) {
        unsigned adc, channel, value;
        if (!z8_adc_decimal(&text, 3, &adc) || !adc || *text++ != '.' ||
            !z8_adc_decimal(&text, 18, &channel) || *text++ != '=' ||
            !z8_adc_decimal(&text, 4095, &value) || seen[adc - 1][channel]) { return false; }
        seen[adc - 1][channel] = true; next[adc - 1][channel] = value;
        if (!*text) { break; }
        if (*text++ != ':' || !*text) { return false; }
    }
    memcpy(values, next, sizeof(next)); return true;
}
#endif
