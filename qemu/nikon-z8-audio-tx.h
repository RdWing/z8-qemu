/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright (C) 2026 RdWing
 * Bounded channel-0 audio TX sink. No DAC, codec or physical rate claim.
 * Only mapped 32-bit single descriptors targeting the original TX FIFO are
 * accepted. Source bytes are read before the existing DMA status/IRQ changes.
 */
#define Z8_AUDIO_TX_BUDGET (16u * 1024u * 1024u)

static int serial5_tx_drain_request(NikonZ8State *s, uint64_t *physical,
                                   unsigned *bytes)
{
    if (!s->serial5_tx_drain_model || !s->bootstrap_fixtures ||
        !s->bus_window_fixture || !s->serial_fixture ||
        !(s->serial5_config[0][0] & 0x2000)) {
        return -1;
    }
    int found = -1;
    for (unsigned ch = 0; ch < 24; ch++) {
        uint32_t *r = s->peripheral24[ch];
        if (!(r[0] & 0x80000000) || r[6] != 0x0e200104) {
            continue;
        }
        unsigned length = ((r[0] & 0xffff) + 1) * 4;
        uint64_t source;
        if (found >= 0 || ((r[0] >> 24) & 0x3f) != 27 ||
            (r[0] & 0x40ff0000) || (r[1] & 0x70000) ||
            (r[1] & ~0x001f0000u) != 0x29e00000 ||
            (r[2] & ~0x404u) || r[3] ||
            !(s->peripheral_global[ch / 8] & 0x80000000) ||
            (s->serial5_config[0][0] & 2) || (r[4] & 3) ||
            !pdma_ram_address(s, 0, r[4], length, &source)) {
            return -1;
        }
        found = ch;
        *physical = source;
        *bytes = length;
    }
    return found;
}

static void serial5_tx_drain_tick(void *opaque)
{
    NikonZ8State *s = opaque;
    uint64_t source = 0;
    unsigned bytes = 0;
    int channel = serial5_tx_drain_request(s, &source, &bytes);
    if (channel < 0 || s->serial5_tx_drain_fault) {
        return;
    }
    if (bytes > Z8_AUDIO_TX_BUDGET - s->serial5_tx_drain_bytes ||
        s->serial5_tx_drain_jobs >= 1024) {
        s->serial5_tx_drain_fault = "bounded-tx-budget-exhausted";
        return;
    }
    g_autofree uint8_t *data = g_malloc(bytes);
    if (address_space_read(&address_space_memory, source, MEMTXATTRS_UNSPECIFIED,
                           data, bytes) != MEMTX_OK) {
        s->serial5_tx_drain_fault = "mapped-source-read-failed";
        return;
    }
    g_checksum_update(s->serial5_tx_drain_hash, data, bytes);
    s->serial5_tx_drain_bytes += bytes;
    s->serial5_tx_drain_jobs++;
    s->serial5_tx_drain_last_source = source;
    pdma_progress(s, channel, 0);
    /* A second descriptor, if any, is a separate transfer and deadline. */
    serial5_tx_drain_schedule(s);
}

static void serial5_tx_drain_schedule(NikonZ8State *s)
{
    if (!s->serial5_tx_drain_timer) {
        return;
    }
    uint64_t source = 0;
    unsigned bytes = 0;
    if (s->serial5_tx_drain_fault ||
        serial5_tx_drain_request(s, &source, &bytes) < 0) {
        timer_del(s->serial5_tx_drain_timer);
    } else if (!timer_pending(s->serial5_tx_drain_timer)) {
        /* Functional clock separation only; not a measured sample rate. */
        timer_mod(s->serial5_tx_drain_timer,
                  qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + 1000000);
    }
}

static bool serial5_tx_drain_read(NikonZ8State *s, hwaddr addr,
                                  uint64_t *value, unsigned size)
{
    if (!s->serial5_tx_drain_model || !s->serial5_tx_drain_jobs ||
        s->serial5_tx_drain_fault || size != 4 || addr != 0x0e20011c) {
        return false;
    }
    /* Only the empty FIFO after a consumed descriptor is covered. An armed
     * replacement, including an unsupported descriptor, is not empty. */
    for (unsigned ch = 0; ch < 24; ch++) {
        if ((s->peripheral24[ch][0] & 0x80000000) &&
            s->peripheral24[ch][6] == 0x0e200104) {
            return false;
        }
    }
    *value = 0;
    s->serial5_tx_drain_empty_reads++;
    return true;
}

static bool get_serial5_tx_drain_model(Object *obj, Error **errp)
{
    return NIKON_Z8_LAB(obj)->serial5_tx_drain_model;
}

static void set_serial5_tx_drain_model(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    if (s->serial5_config[0][0] & 0x3000 || s->serial5_tx_drain_jobs) {
        error_setg(errp, "TX drain selection is immutable after a stream starts");
        return;
    }
    if (value && (!s->bootstrap_fixtures || !s->bus_window_fixture ||
                  !s->serial_fixture)) {
        error_setg(errp, "TX drain requires explicit register, bus and serial fixtures");
        return;
    }
    if (value && !s->serial5_tx_drain_timer) {
        s->serial5_tx_drain_timer = timer_new_ns(QEMU_CLOCK_VIRTUAL,
                                               serial5_tx_drain_tick, s);
        s->serial5_tx_drain_hash = g_checksum_new(G_CHECKSUM_SHA256);
    }
    s->serial5_tx_drain_model = value;
    serial5_tx_drain_schedule(s);
}

static char *get_serial5_tx_drain_state(Object *obj, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    uint64_t source = 0;
    unsigned bytes = 0;
    int channel = serial5_tx_drain_request(s, &source, &bytes);
    char digest[65] = "";
    if (s->serial5_tx_drain_hash) {
        GChecksum *copy = g_checksum_copy(s->serial5_tx_drain_hash);
        g_strlcpy(digest, g_checksum_get_string(copy), sizeof(digest));
        g_checksum_free(copy);
    }
    return g_strdup_printf("{\"enabled\":%s,\"dma_channel\":%d,"
        "\"pending_bytes\":%u,\"pending_source\":%"PRIu64","
        "\"jobs\":%"PRIu64",\"bytes\":%"PRIu64",\"last_source\":%"PRIu64","
        "\"sha256\":\"%s\",\"empty_reads\":%"PRIu64",\"fault\":\"%s\","
        "\"budget_bytes\":%u,\"delay_ns\":1000000,"
        "\"dac_output\":false,\"physical_timing_verified\":false}",
        s->serial5_tx_drain_model ? "true" : "false", channel,
        bytes, source, s->serial5_tx_drain_jobs, s->serial5_tx_drain_bytes,
        s->serial5_tx_drain_last_source, digest, s->serial5_tx_drain_empty_reads,
        s->serial5_tx_drain_fault ? s->serial5_tx_drain_fault : "",
        Z8_AUDIO_TX_BUDGET);
}
