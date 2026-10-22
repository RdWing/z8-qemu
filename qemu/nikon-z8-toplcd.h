/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright (C) 2026 RdWing: Z8/QEMU 11 adaptation.
 * Panel mechanism adapted from the pinned Z63 donor; see source-map receipts.
 *
 * Original Z8 EX03.00 builds 168 rows of 18 bytes (144 one-bit pixels).
 * The gate byte for renderer row y is bit_reverse8(168-y). The model stores
 * panel line 1 first and the first shifted bit at the left; it does not infer
 * the panel's physical rotation or appearance from the Z63 reference.
 *
 * SPI2 packets are framed by active-high SCS (PA4). Mode 0x80 updates lines:
 * gate address, 18 data bytes, one dummy, repeated, then a zero trailer.
 * Mode 0x20 clears memory to white. PE8 is DISP; PD11 starts the panel supply
 * substitute. Z8's initializer selects ready descriptor ID 1 (PA1), whereas
 * the donor selects ID 49 (PD1). A memory LCD has no ready output of its own;
 * the external supply/peer identity remains unqualified. DECLARED: pull ready
 * low during the start pulse and release it 5 ms after that pulse ends.
 *
 * Only complete lines commit. Invalid addresses, partial rows and bytes with
 * SCS low cannot replace pixels. QOM exposes retained memory and read-only
 * counters. DISP low blanks the viewer without erasing retained memory.
 * VCOM, electrical limits, physical response and optical color are not modeled.
 */

#ifndef HW_ARM_NIKON_Z8_TOPLCD_H
#define HW_ARM_NIKON_Z8_TOPLCD_H

#define Z8_TOPLCD_W        144
#define Z8_TOPLCD_H        168
#define Z8_TOPLCD_STRIDE   (Z8_TOPLCD_W / 8)
#define Z8_TOPLCD_READY_NS (5 * SCALE_MS)      /* declared, see above */

typedef struct Z8TopLcd {
    bool scs, disp;
    enum {
        Z8_TOPLCD_MODE,            /* the first byte after SCS rises */
        Z8_TOPLCD_ADDR,
        Z8_TOPLCD_DATA,
        Z8_TOPLCD_DUMMY,
        Z8_TOPLCD_IDLE,            /* the rest of the packet is dummy */
    } state;
    unsigned line, at;
    uint8_t row[Z8_TOPLCD_STRIDE];
    uint8_t mem[Z8_TOPLCD_H][Z8_TOPLCD_STRIDE];   /* 1 = white */
    bool dirty;
    Z8Stm32Gpio *ready_gpio;       /* the ready line, an MCU input */
    unsigned ready_pin;
    QEMUTimer *ready_timer;

    uint64_t packets, lines, clears;
    unsigned named;                 /* oddities reported so far */
} Z8TopLcd;

#define Z8_TOPLCD_NAMED    8

static void z8_toplcd_odd(Z8TopLcd *t, const char *fmt, ...)
    G_GNUC_PRINTF(2, 3);

static void z8_toplcd_odd(Z8TopLcd *t, const char *fmt, ...)
{
    va_list ap;
    g_autofree char *msg = NULL;

    if (t->named >= Z8_TOPLCD_NAMED) {
        return;
    }
    va_start(ap, fmt);
    msg = g_strdup_vprintf(fmt, ap);
    va_end(ap);
    error_report("Z8_TOPLCD: %s%s", msg, ++t->named == Z8_TOPLCD_NAMED ?
                 " (further oddities not named)" : "");
}

/* What the panel shows, to the live file, if it changed. */
/* Model memory is exposed through the Z8 MCU QOM interface. */
static void z8_toplcd_publish(Z8TopLcd *t) { t->dirty=false; }

/* A byte shifted in. Only while SCS is high does the panel listen. */
static void z8_toplcd_byte(void *opaque, unsigned inst, uint16_t word)
{
    Z8TopLcd *t = opaque;
    uint8_t b = word;

    if (!t->scs) {
        z8_toplcd_odd(t, "0x%02x arrived with SCS low and was dropped",
                       b);
        return;
    }
    switch (t->state) {
    case Z8_TOPLCD_MODE:
        t->packets++;
        if (b & 0x80) {                                 /* M0 */
            t->state = Z8_TOPLCD_ADDR;
        } else {
            if (b & 0x20) {                             /* M2 */
                memset(t->mem, 0xff, sizeof(t->mem));
                t->clears++;
                t->dirty = true;
            }
            t->state = Z8_TOPLCD_IDLE;
        }
        break;
    case Z8_TOPLCD_ADDR:
        /* The address goes LSB first: reversed in an MSB-first byte. */
        t->line = revbit8(b);
        if (t->line == 0) {                             /* the trailer */
            t->state = Z8_TOPLCD_IDLE;
        } else if (t->line > Z8_TOPLCD_H) {
            z8_toplcd_odd(t, "gate line %u (byte 0x%02x) is past the "
                           "panel's %u", t->line, b, Z8_TOPLCD_H);
            t->state = Z8_TOPLCD_IDLE;
        } else {
            t->at = 0;
            t->state = Z8_TOPLCD_DATA;
        }
        break;
    case Z8_TOPLCD_DATA:
        t->row[t->at++] = b;
        if (t->at == Z8_TOPLCD_STRIDE) {
            if (memcmp(t->mem[t->line - 1], t->row, sizeof(t->row))) {
                memcpy(t->mem[t->line - 1], t->row, sizeof(t->row));
                t->dirty = true;
            }
            t->lines++;
            t->state = Z8_TOPLCD_DUMMY;
        }
        break;
    case Z8_TOPLCD_DUMMY:
        t->state = Z8_TOPLCD_ADDR;
        break;
    case Z8_TOPLCD_IDLE:
        break;
    }
}

static void z8_toplcd_scs(Z8TopLcd *t, bool level)
{
    if (level == t->scs) {
        return;
    }
    t->scs = level;
    if (level) {
        t->state = Z8_TOPLCD_MODE;
        return;
    }
    if (t->state == Z8_TOPLCD_DATA) {
        z8_toplcd_odd(t, "SCS fell %u bytes into line %u", t->at, t->line);
    }
    /* The end of a packet: what the panel now shows. */
    if (t->packets == 1) {
        error_report("Z8_TOPLCD: the first packet (%" PRIu64 " clear, "
                     "%" PRIu64 " lines)", t->clears, t->lines);
    }
    z8_toplcd_publish(t);
}

static void z8_toplcd_disp(Z8TopLcd *t, bool level)
{
    if (level == t->disp) {
        return;
    }
    t->disp = level;
    error_report("Z8_TOPLCD: DISP %s after %" PRIu64 " packets",
                 level ? "high: the panel shows its memory"
                       : "low: the panel is blank", t->packets);
    t->dirty = true;
    z8_toplcd_publish(t);
}

/* The board-selected start pulse: ready goes low with it and comes back
 * up a little after it (declared, see above). */
static void z8_toplcd_start(Z8TopLcd *t, bool level)
{
    if (level) {
        timer_del(t->ready_timer);
        z8_stm32_gpio_drive(t->ready_gpio, t->ready_pin, false);
    } else {
        timer_mod(t->ready_timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) +
                  Z8_TOPLCD_READY_NS);
    }
}

static void z8_toplcd_ready(void *opaque)
{
    Z8TopLcd *t = opaque;

    error_report("Z8_TOPLCD: ready line P%c%u released (declared: %u ms "
                 "after the start pulse)", 'A' + t->ready_gpio->port,
                 t->ready_pin, (unsigned)(Z8_TOPLCD_READY_NS / SCALE_MS));
    z8_stm32_gpio_drive(t->ready_gpio, t->ready_pin, true);
}

/* The panel at power-on: memory undefined (shown white; the MCU clears it
 * before raising DISP), SCS and DISP low, the ready line left to its
 * pull-up. */
static void z8_toplcd_init(Z8TopLcd *t, const char *live,
                            Z8Stm32Gpio *ready, unsigned ready_pin)
{
    memset(t->mem, 0xff, sizeof(t->mem));
    t->ready_gpio = ready;
    t->ready_pin = ready_pin;
    t->ready_timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, z8_toplcd_ready, t);
    (void)live; /* Native app reads bounded panel memory through QOM. */
}

#endif
