/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright (C) 2026 RdWing: QEMU 11 adaptation.
 * Adapted observation mechanisms from RdWing/z63-qemu z63watch/z63ftrace/z63log.
 * Explicit user addresses only: no donor firmware hooks, stack scan or writes.
 */
#include <errno.h>
#include <fcntl.h>
#include <glib.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <qemu-plugin.h>

QEMU_PLUGIN_EXPORT int qemu_plugin_version = QEMU_PLUGIN_VERSION;
#if QEMU_PLUGIN_VERSION < 7
#error This adaptation requires the QEMU 11 plugin API (version 7).
#endif

#define MAX_CPUS 16
#define MAX_CALLS 32
#define MAX_SITES 4096
typedef struct { uint64_t pc, address; unsigned cpu, kind; } Site;
typedef struct {
    struct qemu_plugin_register *arg[5], *link;
    bool arg_present[5], link_present, aarch64;
} Registers;
static Registers regs[MAX_CPUS];
static uint64_t calls[MAX_CALLS], lo, hi, pclo, pchi, limit = 10000, per_site = 4;
static unsigned n_calls, options;
static int selected_cpu = -1;
static bool watch;
static enum qemu_plugin_mem_rw access_mode = QEMU_PLUGIN_MEM_W;
static const char *access_name = "write";
static bool app_log;
static uint64_t app_log_pc;
static FILE *out;
static GMutex lock;
static GHashTable *sites;
static uint64_t emitted, suppressed;
static int64_t started;

static guint site_hash(gconstpointer p)
{
    const Site *s = p;
    return (guint)(s->pc ^ (s->pc >> 32) ^ s->address ^
                   (s->address >> 32) ^ (s->cpu << 8) ^ s->kind);
}
static gboolean site_equal(gconstpointer a, gconstpointer b)
{
    const Site *x = a, *y = b;
    return x->pc == y->pc && x->address == y->address &&
           x->cpu == y->cpu && x->kind == y->kind;
}
/* Caller holds lock. Both distinct sites and output records are bounded. */
static bool admit(unsigned cpu, unsigned kind, uint64_t pc, uint64_t address)
{
    Site key = { pc, address, cpu, kind };
    uint64_t *count = g_hash_table_lookup(sites, &key);
    if (emitted >= limit || (count && *count >= per_site) ||
        (!count && g_hash_table_size(sites) >= MAX_SITES)) {
        suppressed++;
        return false;
    }
    if (!count) {
        Site *copy = g_new(Site, 1);
        *copy = key; count = g_new0(uint64_t, 1);
        g_hash_table_insert(sites, copy, count);
    }
    (*count)++; emitted++;
    return true;
}
static bool read_reg(struct qemu_plugin_register *reg, bool present, uint64_t *value)
{
    g_autoptr(GByteArray) bytes = g_byte_array_new();
    /* Register zero may have a NULL-valued opaque handle in QEMU 11.
     * Presence comes from the descriptor, never from the pointer value. */
    if (!present || !qemu_plugin_read_register(reg, bytes) ||
        (bytes->len != 4 && bytes->len != 8)) {
        return false;
    }
    *value = 0;
    for (unsigned i = 0; i < bytes->len; i++) { *value |= (uint64_t)bytes->data[i] << (8 * i); }
    return true;
}
static void print_reg(struct qemu_plugin_register *reg, bool present)
{
    uint64_t value;
    if (read_reg(reg, present, &value)) { fprintf(out, "\"0x%" PRIx64 "\"", value); }
    else { fputs("null", out); }
}
static void print_low32(struct qemu_plugin_register *reg, bool present)
{
    uint64_t value;
    if (read_reg(reg, present, &value)) { fprintf(out, "%" PRIu32, (uint32_t)value); }
    else { fputs("null", out); }
}
static void vcpu_init(unsigned idx, void *unused)
{
    (void)unused;
    if (idx >= MAX_CPUS) { return; }
    g_autoptr(GArray) list = qemu_plugin_get_registers();
    for (guint i = 0; list && i < list->len; i++) {
        qemu_plugin_reg_descriptor *d = &g_array_index(list, qemu_plugin_reg_descriptor, i);
        for (unsigned a = 0; a < 5; a++) {
            char x[4], r[4];
            snprintf(x, sizeof(x), "x%u", a); snprintf(r, sizeof(r), "r%u", a);
            if (!strcmp(d->name, x) || !strcmp(d->name, r)) {
                regs[idx].arg[a] = d->handle; regs[idx].arg_present[a] = true;
            }
            if (!strcmp(d->name, x)) { regs[idx].aarch64 = true; }
        }
        if (!strcmp(d->name, "x30") || !strcmp(d->name, "lr") || !strcmp(d->name, "r14")) {
            regs[idx].link = d->handle;
            regs[idx].link_present = true;
        }
    }
}
static bool cpu_allowed(unsigned idx)
{
    return idx < MAX_CPUS && (selected_cpu < 0 || idx == (unsigned)selected_cpu);
}
static void call_hit(unsigned idx, void *opaque)
{
    if (!cpu_allowed(idx)) { return; }
    uint64_t pc = *(uint64_t *)opaque;
    g_mutex_lock(&lock);
    if (admit(idx, 0, pc, 0)) {
        fprintf(out, "{\"event\":\"call\",\"host_us\":%" PRId64 ",\"cpu\":%u,\"pc\":\"0x%" PRIx64 "\",\"args\":[",
                g_get_monotonic_time() - started, idx, pc);
        for (unsigned a = 0; a < 4; a++) {
            if (a) { fputc(',', out); }
            print_reg(regs[idx].arg[a], regs[idx].arg_present[a]);
        }
        fputs("],\"link\":", out); print_reg(regs[idx].link, regs[idx].link_present); fputs("}\n", out);
    }
    g_mutex_unlock(&lock);
}
/* Explicit AArch64 application-ring register schema. The object is an opaque
 * address: never dereference it, including for a module ID. Debug memory reads
 * can have MMIO side effects, and a call entry does not establish a valid object
 * or a completed ring write. No addresses, module names or severity names are
 * inferred here. */
static void app_log_hit(unsigned idx, void *unused)
{
    (void)unused;
    if (!cpu_allowed(idx)) { return; }
    bool supported = regs[idx].aarch64;
    g_mutex_lock(&lock);
    if (admit(idx, 2, app_log_pc, 0)) {
        fprintf(out, "{\"event\":\"app_log\",\"host_us\":%" PRId64 ",\"cpu\":%u,\"pc\":\"0x%" PRIx64 "\",\"abi_available\":%s,\"object\":",
                g_get_monotonic_time() - started, idx, app_log_pc,
                supported ? "true" : "false");
        print_reg(regs[idx].arg[0], supported && regs[idx].arg_present[0]);
        fputs(",\"module_id\":null,\"module_id_source\":\"not_read\",\"selector\":", out);
        print_low32(regs[idx].arg[1], supported && regs[idx].arg_present[1]);
        fputs(",\"payload\":[", out);
        for (unsigned a = 2; a < 5; a++) {
            if (a != 2) { fputc(',', out); }
            print_low32(regs[idx].arg[a], supported && regs[idx].arg_present[a]);
        }
        fputs("],\"link\":", out);
        print_reg(regs[idx].link, supported && regs[idx].link_present);
        if (!supported) { fputs(",\"reason\":\"unsupported_architecture\"", out); }
        fputs("}\n", out);
    }
    g_mutex_unlock(&lock);
}
static void memory_access(unsigned idx, qemu_plugin_meminfo_t info, uint64_t address, void *opaque)
{
    if (!cpu_allowed(idx)) { return; }
    bool write = qemu_plugin_mem_is_store(info);
    unsigned shift = qemu_plugin_mem_size_shift(info);
    if (shift > 4) { return; }
    unsigned size = 1u << shift;
    /* Include overlapping accesses, without overflowing address+size. */
    if (address >= hi || (address < lo && lo - address >= size)) { return; }
    qemu_plugin_mem_value value = qemu_plugin_mem_get_value(info);
    uint64_t low = 0, high = 0;
    switch (value.type) {
    case QEMU_PLUGIN_MEM_VALUE_U8: low = value.data.u8; break;
    case QEMU_PLUGIN_MEM_VALUE_U16: low = value.data.u16; break;
    case QEMU_PLUGIN_MEM_VALUE_U32: low = value.data.u32; break;
    case QEMU_PLUGIN_MEM_VALUE_U64: low = value.data.u64; break;
    case QEMU_PLUGIN_MEM_VALUE_U128: low = value.data.u128.low; high = value.data.u128.high; break;
    default: return;
    }
    uint64_t pc = (uintptr_t)opaque;
    g_mutex_lock(&lock);
    if (admit(idx, write ? 1 : 3, pc, address)) {
        fprintf(out, "{\"event\":\"%s\",\"host_us\":%" PRId64 ",\"cpu\":%u,\"pc\":\"0x%" PRIx64 "\",\"address\":\"0x%" PRIx64 "\",\"size\":%u,\"value\":\"0x",
                write ? "store" : "read", g_get_monotonic_time() - started, idx, pc, address, size);
        if (value.type == QEMU_PLUGIN_MEM_VALUE_U128) { fprintf(out, "%" PRIx64 "%016" PRIx64, high, low); }
        else { fprintf(out, "%" PRIx64, low); }
        fputs("\"}\n", out);
    }
    g_mutex_unlock(&lock);
}
static void translated(struct qemu_plugin_tb *tb, void *unused)
{
    (void)unused;
    for (size_t i = 0; i < qemu_plugin_tb_n_insns(tb); i++) {
        struct qemu_plugin_insn *insn = qemu_plugin_tb_get_insn(tb, i);
        uint64_t pc = qemu_plugin_insn_vaddr(insn);
        for (unsigned k = 0; k < n_calls; k++) {
            if (calls[k] == pc) {
                qemu_plugin_register_vcpu_insn_exec_cb(insn, call_hit, QEMU_PLUGIN_CB_R_REGS, &calls[k]);
            }
        }
        if (app_log && app_log_pc == pc) {
            qemu_plugin_register_vcpu_insn_exec_cb(insn, app_log_hit, QEMU_PLUGIN_CB_R_REGS, NULL);
        }
        if (watch && pc >= pclo && pc < pchi) {
            qemu_plugin_register_vcpu_mem_cb(insn, memory_access, QEMU_PLUGIN_CB_NO_REGS,
                                            access_mode, (void *)(uintptr_t)pc);
        }
    }
}
static void finished(void *unused)
{
    (void)unused;
    fprintf(out, "{\"event\":\"summary\",\"emitted\":%" PRIu64 ",\"suppressed\":%" PRIu64 ",\"sites\":%u}\n",
            emitted, suppressed, g_hash_table_size(sites));
    fclose(out); g_hash_table_destroy(sites);
}
static bool number(const char *s, uint64_t *v)
{
    if (!s || !g_ascii_isdigit(*s)) { return false; }
    char *end; errno = 0; *v = g_ascii_strtoull(s, &end, 0);
    return !errno && !*end;
}
QEMU_PLUGIN_EXPORT int qemu_plugin_install(qemu_plugin_id_t id, const qemu_info_t *info, int argc, char **argv)
{
    const char *path = NULL;
    if (!info->system_emulation || strcmp(info->target_name, "aarch64")) { return -1; }
    const char *names[] = { "out", "cpu", "calls", "lo", "hi", "pclo", "pchi", "limit", "per_site", "app_log", "access" };
    for (int i = 0; i < argc; i++) {
        g_auto(GStrv) kv = g_strsplit(argv[i], "=", 2);
        unsigned key;
        for (key = 0; key < G_N_ELEMENTS(names); key++) { if (!strcmp(kv[0], names[key])) { break; } }
        if (!kv[1] || !*kv[1] || key == G_N_ELEMENTS(names) || (options & (1u << key))) { return -1; }
        options |= 1u << key;
        uint64_t n;
        if (key == 0) {
            path = strchr(argv[i], '=') + 1;
        } else if (key == 2) {
            g_auto(GStrv) list = g_strsplit(kv[1], ":", -1);
            for (char **p = list; *p; p++) {
                if (n_calls == MAX_CALLS || !number(*p, &n) || !n || (n & 1)) { return -1; }
                for (unsigned k = 0; k < n_calls; k++) { if (calls[k] == n) { return -1; } }
                calls[n_calls++] = n;
            }
        } else if (key == 10) {
            if (!strcmp(kv[1], "read")) { access_mode = QEMU_PLUGIN_MEM_R; access_name = "read"; }
            else if (!strcmp(kv[1], "write")) { access_mode = QEMU_PLUGIN_MEM_W; access_name = "write"; }
            else if (!strcmp(kv[1], "both")) { access_mode = QEMU_PLUGIN_MEM_RW; access_name = "both"; }
            else { return -1; }
        } else {
            if (!number(kv[1], &n)) { return -1; }
            switch (key) {
            case 1: if (n >= MAX_CPUS) { return -1; } selected_cpu = n; break;
            case 3: lo = n; break; case 4: hi = n; break;
            case 5: pclo = n; break; case 6: pchi = n; break;
            case 7: if (!n || n > 1000000) { return -1; } limit = n; break;
            case 8: if (!n || n > 1000000) { return -1; } per_site = n; break;
            case 9: if (!n || (n & 3)) { return -1; } app_log_pc = n; app_log = true; break;
            default: return -1;
            }
        }
    }
    unsigned watch_options = options & 0x78;
    watch = watch_options == 0x78;
    if (!path || (!n_calls && !watch && !app_log) || (watch_options && !watch) ||
        (watch && (lo >= hi || pclo >= pchi)) || ((options & (1u << 10)) && !watch)) { return -1; }
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW, 0600);
    if (fd < 0) { return -1; }
    out = fdopen(fd, "w");
    if (!out) { close(fd); return -1; }
    setvbuf(out, NULL, _IOLBF, 0);
    sites = g_hash_table_new_full(site_hash, site_equal, g_free, g_free);
    started = g_get_monotonic_time();
    fprintf(out, "{\"event\":\"start\",\"clock\":\"host_monotonic_us\",\"calls\":%u,\"watch\":%s,\"access\":\"%s\",\"app_log\":%s,\"limit\":%" PRIu64 ",\"per_site\":%" PRIu64 "}\n",
            n_calls, watch ? "true" : "false", access_name, app_log ? "true" : "false", limit, per_site);
    qemu_plugin_register_vcpu_init_cb(id, vcpu_init, NULL);
    qemu_plugin_register_vcpu_tb_trans_cb(id, translated, NULL);
    qemu_plugin_register_atexit_cb(id, finished, NULL);
    return 0;
}
