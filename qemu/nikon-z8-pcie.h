/* SPDX-License-Identifier: GPL-2.0-or-later
 * Copyright (C) 2026 RdWing
 * Opt-in port2 functional DBI/unrolled-ATU adapter for upstream DesignWare.
 * Native initialization matches these interfaces; physical IP identity and
 * Nikon interrupt routing are unproved. No IRQ is wired to a guessed GIC pin.
 */
#define Z8_PCIE_DBI UINT64_C(0x1a800000)
#define Z8_PCIE_ATU (Z8_PCIE_DBI + 0x300000)
#define Z8_PCIE_CPU_WINDOW UINT64_C(0x600000000)

static void z8_pcie_intx_update(NikonZ8State *s)
{
    if (s->pcie_intx_model) {
        qemu_set_irq(s->pcie_legacy_irq, s->pcie_intx_pending &&
                     s->pcie_wrapper[1][1] && !s->pcie_wrapper[1][0]);
    }
}

static void z8_pcie_intx_input(void *opaque, int pin, int level)
{
    NikonZ8State *s = opaque;
    uint32_t bit = 1U << (15 - pin);
    if (level && !(s->pcie_intx_levels & bit)) {
        s->pcie_intx_pending |= bit;
        s->pcie_intx_assertions++;
    }
    if (level) {
        s->pcie_intx_levels |= bit;
    } else {
        s->pcie_intx_levels &= ~bit;
    }
    z8_pcie_intx_update(s);
}

static PCIDevice *z8_pcie_root(NikonZ8State *s)
{
    return PCI_DEVICE(&DESIGNWARE_PCIE_HOST(s->pcie_dbi_host)->root);
}

static uint32_t z8_pcie_wrapper_link_input(NikonZ8State *s)
{
    PCIBus *bus = &PCI_BRIDGE(z8_pcie_root(s))->sec_bus;
    /* Functional endpoint-present input for the original low-six-bit link
     * query. This is not a PHY/LTSSM simulation or a measured Nikon value.
     * Native4028cf50 selects wrapper+58 before4028d0e8 sets bit0 and polls
     * +b4 for0x11. The separate+258 path corresponds to the other lane. */
    bool endpoint = pci_find_device(bus, pci_bus_num(bus), PCI_DEVFN(0, 0));
    uint32_t value = endpoint && s->pcie_wrapper[1][1] && !s->pcie_wrapper[1][0]
                     ? 0x11 : 0;
    if (s->pcie_link_status_reads++ < 16) {
        fprintf(stderr, "Z8_PCIE_LINK_INPUT endpoint=%u enable=%x reset=%x value=%x; functional input\n",
                endpoint, s->pcie_wrapper[1][1], s->pcie_wrapper[1][0], value);
    }
    return value;
}

static uint64_t z8_pcie_dbi_read(void *opaque, hwaddr addr, unsigned size)
{
    NikonZ8State *s = opaque;
    if ((size != 1 && size != 2 && size != 4) || (addr & (size - 1))) {
        unknown_access(s, Z8_PCIE_DBI + addr, 0, size, false);
        return 0;
    }
    if (addr == 0x8bc && size == 4) {
        return s->pcie_dbi_ro_enable;
    }
    s->pcie_dbi_reads++;
    return pci_host_config_read_common(z8_pcie_root(s), addr, 4096, size);
}

static void z8_pcie_dbi_write(void *opaque, hwaddr addr, uint64_t value,
                              unsigned size)
{
    NikonZ8State *s = opaque;
    if ((size != 1 && size != 2 && size != 4) || (addr & (size - 1))) {
        unknown_access(s, Z8_PCIE_DBI + addr, value, size, true);
        return;
    }
    if (addr == 0x8bc) {
        if (size != 4 || value > 1) {
            unknown_access(s, Z8_PCIE_DBI + addr, value, size, true);
            return;
        }
        /* Retained DBI programming-mode control. PCI config writes currently
         * use upstream writable masks; no blanket bypass of readonly fields. */
        s->pcie_dbi_ro_enable = value;
        return;
    }
    s->pcie_dbi_writes++;
    pci_host_config_write_common(z8_pcie_root(s), addr, 4096, value, size);
}

static bool z8_pcie_atu_select(NikonZ8State *s, hwaddr addr, unsigned size,
                                unsigned *reg, unsigned *selection)
{
    static const unsigned legacy[] = {0x904, 0x908, 0x90c, 0x910,
                                      0x914, 0x918, 0x91c};
    unsigned region = addr / 0x200;
    unsigned offset = addr % 0x100;
    if (size != 4 || (addr & 3) || region >= DESIGNWARE_PCIE_NUM_VIEWPORTS ||
        offset >= sizeof(legacy)) {
        return false;
    }
    *reg = legacy[offset / 4];
    *selection = region | ((addr & 0x100) ? (1U << 31) : 0);
    return true;
}

static uint64_t z8_pcie_atu_read(void *opaque, hwaddr addr, unsigned size)
{
    NikonZ8State *s = opaque;
    unsigned reg, selection;
    if (!z8_pcie_atu_select(s, addr, size, &reg, &selection)) {
        unknown_access(s, Z8_PCIE_ATU + addr, 0, size, false);
        return 0;
    }
    PCIDevice *d = z8_pcie_root(s);
    PCIDeviceClass *dc = PCI_DEVICE_GET_CLASS(d);
    uint32_t previous = dc->config_read(d, 0x900, 4);
    dc->config_write(d, 0x900, selection, 4);
    uint32_t value = dc->config_read(d, reg, 4);
    dc->config_write(d, 0x900, previous, 4);
    return value;
}

static void z8_pcie_atu_write(void *opaque, hwaddr addr, uint64_t value,
                              unsigned size)
{
    NikonZ8State *s = opaque;
    unsigned reg, selection;
    if (!z8_pcie_atu_select(s, addr, size, &reg, &selection) ||
        (reg == 0x904 && value != 0 && value != 4 && value != 5) ||
        (reg == 0x908 && value != 0 && value != 0x80000000) ||
        ((reg == 0x910 || reg == 0x91c) && value > 255)) {
        unknown_access(s, Z8_PCIE_ATU + addr, value, size, true);
        return;
    }
    DesignwarePCIERoot *root = &DESIGNWARE_PCIE_HOST(s->pcie_dbi_host)->root;
    DesignwarePCIEViewport *v = &root->viewports[selection >> 31][selection & 3];
    if (reg == 0x908 && value) {
        uint64_t limit = (v->base & ~UINT64_C(0xffffffff)) | v->limit;
        if (limit < v->base || v->base >= (UINT64_C(1) << 40) ||
            (selection >> 31 && v->cr[0] != 0)) {
            unknown_access(s, Z8_PCIE_ATU + addr, value, size, true);
            return;
        }
    }
    PCIDevice *d = PCI_DEVICE(root);
    PCIDeviceClass *dc = PCI_DEVICE_GET_CLASS(d);
    uint32_t previous = dc->config_read(d, 0x900, 4);
    dc->config_write(d, 0x900, selection, 4);
    dc->config_write(d, reg, value, 4);
    dc->config_write(d, 0x900, previous, 4);
    s->pcie_atu_writes++;
}

static const MemoryRegionOps z8_pcie_dbi_ops = {
    .read = z8_pcie_dbi_read, .write = z8_pcie_dbi_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4, .unaligned = true },
    .impl = { .min_access_size = 1, .max_access_size = 4, .unaligned = true },
};

static const MemoryRegionOps z8_pcie_atu_ops = {
    .read = z8_pcie_atu_read, .write = z8_pcie_atu_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4, .unaligned = true },
    .impl = { .min_access_size = 1, .max_access_size = 4, .unaligned = true },
};

/* Native port2 setup4028ca18..cb84 programs local32-bit ATU offsets; the
 * endpoint accessor4028d6e8 uses the separate 0x600000000 CPU aperture.
 * CFG0 addresses the device on this link, without enumerating the synthetic
 * upstream root bridge. Ordinary absolute upstream windows remain available
 * for controlled tests. Physical IP identity/routing are still unproved. */
static uint64_t z8_pcie_cpu_access(NikonZ8State *s, hwaddr addr,
                                    uint64_t value, unsigned size, bool write)
{
    DesignwarePCIERoot *root = &DESIGNWARE_PCIE_HOST(s->pcie_dbi_host)->root;
    if ((size != 1 && size != 2 && size != 4 && size != 8) || (addr & (size - 1))) {
        goto unsupported;
    }
    for (unsigned i = 0; i < DESIGNWARE_PCIE_NUM_VIEWPORTS; i++) {
        DesignwarePCIEViewport *v = &root->viewports[0][i];
        if (!(v->cr[1] & 0x80000000) || v->base >= UINT64_C(0x100000000) ||
            v->limit < v->base || addr < v->base || addr > v->limit ||
            size - 1 > v->limit - addr) {
            continue;
        }
        if (write) {
            s->pcie_cpu_writes++;
        } else {
            s->pcie_cpu_reads++;
        }
        if (v->cr[0] == 4) {
            PCIBus *bus = &PCI_BRIDGE(root)->sec_bus;
            PCIDevice *endpoint = pci_find_device(bus, pci_bus_num(bus),
                                                 (v->target >> 16) & 255);
            uint64_t offset = addr - v->base;
            if (size > 4 || offset >= 4096 || size > 4096 - offset) {
                goto unsupported;
            }
            if (!endpoint) {
                return UINT64_MAX;
            }
            if (write) {
                pci_host_config_write_common(endpoint, offset, 4096, value, size);
                return 0;
            }
            return pci_host_config_read_common(endpoint, offset, 4096, size);
        }
        if (v->cr[0] == 0) {
            uint8_t bytes[8];
            /* Upstream already owns a bounded MEM alias at this local
             * address, including bridge/BAR decode and bus-master checks. */
            if (write) {
                for (unsigned b = 0; b < size; b++) {
                    bytes[b] = value >> (b * 8);
                }
                cpu_physical_memory_write(addr, bytes, size);
                return 0;
            }
            cpu_physical_memory_read(addr, bytes, size);
            value = 0;
            for (unsigned b = 0; b < size; b++) {
                value |= (uint64_t)bytes[b] << (b * 8);
            }
            return value;
        }
        goto unsupported;
    }
unsupported:
    unknown_access(s, Z8_PCIE_CPU_WINDOW + addr, value, size, write);
    return 0;
}

static uint64_t z8_pcie_cpu_read(void *opaque, hwaddr addr, unsigned size)
{
    return z8_pcie_cpu_access(opaque, addr, 0, size, false);
}

static void z8_pcie_cpu_write(void *opaque, hwaddr addr, uint64_t value, unsigned size)
{
    z8_pcie_cpu_access(opaque, addr, value, size, true);
}

static const MemoryRegionOps z8_pcie_cpu_ops = {
    .read = z8_pcie_cpu_read, .write = z8_pcie_cpu_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 8, .unaligned = true },
    .impl = { .min_access_size = 1, .max_access_size = 8, .unaligned = true },
};

static bool get_pcie_dbi_model(Object *obj, Error **errp)
{
    return NIKON_Z8_LAB(obj)->pcie_dbi_model;
}

static void set_pcie_dbi_model(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    if (s->image_ram.ram || s->image_ram.rom_device) {
        error_setg(errp, "pcie-dbi-model is immutable after realization");
        return;
    }
    s->pcie_dbi_model = value;
}

static bool get_pcie_ram_dma_input(Object *obj, Error **errp)
{
    return NIKON_Z8_LAB(obj)->pcie_ram_dma_input;
}

static void set_pcie_ram_dma_input(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    if (s->image_ram.ram || s->image_ram.rom_device) {
        error_setg(errp, "pcie-ram-dma-input is immutable after realization");
        return;
    }
    s->pcie_ram_dma_input = value;
}

static bool get_pcie_image_ram_dma_input(Object *obj, Error **errp)
{ return NIKON_Z8_LAB(obj)->pcie_image_ram_dma_input; }

static void set_pcie_image_ram_dma_input(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    if (s->image_ram.ram || s->image_ram.rom_device) {
        error_setg(errp, "pcie-image-ram-dma-input is immutable after realization"); return;
    }
    s->pcie_image_ram_dma_input = value;
}

static bool get_pcie_intx_model(Object *obj, Error **errp)
{
    return NIKON_Z8_LAB(obj)->pcie_intx_model;
}

static void set_pcie_intx_model(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    if (s->image_ram.ram || s->image_ram.rom_device) {
        error_setg(errp, "pcie-intx-model is immutable after realization");
        return;
    }
    s->pcie_intx_model = value;
}

static char *get_pcie_dbi_state(Object *obj, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    return g_strdup_printf("{\"enabled\":%s,\"dbi_reads\":%" PRIu64
        ",\"dbi_writes\":%" PRIu64 ",\"atu_writes\":%" PRIu64
        ",\"cpu_aperture_reads\":%" PRIu64 ",\"cpu_aperture_writes\":%" PRIu64
        ",\"dbi_ro_enable\":%u,\"ram_dma_input\":%s,\"ram_dma_bytes\":%" PRIu64
        ",\"image_ram_dma_input\":%s,\"image_ram_dma_bytes\":%" PRIu64 ",\"intx_model\":%s,\"intx_levels\":%u,\"intx_pending\":%u"
        ",\"intx_assertions\":%" PRIu64 ",\"intx_acks\":%" PRIu64
        ",\"native_irq_routing_verified\":false,"
        "\"physical_ip_identity_verified\":false,\"camera_acceptance\":false}",
        s->pcie_dbi_model ? "true" : "false", s->pcie_dbi_reads,
        s->pcie_dbi_writes, s->pcie_atu_writes, s->pcie_cpu_reads,
        s->pcie_cpu_writes, s->pcie_dbi_ro_enable,
        s->pcie_ram_dma_input ? "true" : "false",
        s->pcie_ram_dma_input ? MACHINE(s)->ram_size : UINT64_C(0),
        s->pcie_image_ram_dma_input ? "true" : "false",
        s->pcie_image_ram_dma_input ?
            (image_bank_ranges[0].end - image_bank_ranges[0].base) +
            (image_bank_ranges[1].end - image_bank_ranges[1].base) : UINT64_C(0),
        s->pcie_intx_model ? "true" : "false", s->pcie_intx_levels,
        s->pcie_intx_pending, s->pcie_intx_assertions, s->pcie_intx_acks);
}

static void z8_pcie_init(NikonZ8State *s, MemoryRegion *mem, DeviceState *gic)
{
    if (!s->pcie_dbi_model) {
        return;
    }
    DeviceState *dev = qdev_new(TYPE_DESIGNWARE_PCIE_HOST);
    object_property_add_child(OBJECT(s), "pcie-host", OBJECT(dev));
    s->pcie_dbi_host = dev;
    sysbus_realize_and_unref(SYS_BUS_DEVICE(dev), &error_fatal);
    if (s->pcie_intx_model) {
        /* Z8 original4028b360 registers4028b524 at INTID0x95.
         * That ISR reads/W1Cs wrapper+e8, dispatching INTA..D bits15..12.
         * ZR independently registers4028b5c8 through40e00710 with
         * W0=0x95 at4028b3f8; its ISR uses the same wrapper and W1C bits.
         * Physical hardware routing is not established. */
        s->pcie_legacy_irq = qdev_get_gpio_in(gic, 0x95 - 32);
        for (unsigned i = 0; i < 4; i++) {
            sysbus_connect_irq(SYS_BUS_DEVICE(dev), i,
                               qemu_allocate_irq(z8_pcie_intx_input, s, i));
        }
    }
    if (s->pcie_ram_dma_input) {
        /* Native run432 programs a1456c000 as ASQ without inbound ATU
         * writes. Upstream's default identity aperture ends at4GiB.
         * Explicit functional input: expose only the allocated work RAM,
         * never the system MMIO/ROM address space. Programmed inbound ATU
         * windows (-1) and endpoint BARs (0) take priority over this (-2).
         * Physical Nikon inbound routing remains unverified. */
        DesignwarePCIEHost *host = DESIGNWARE_PCIE_HOST(dev);
        memory_region_init_alias(&s->pcie_ram_dma, OBJECT(s),
                                 "z8.pcie-work-ram-input", MACHINE(s)->ram,
                                 0, MACHINE(s)->ram_size);
        memory_region_add_subregion_overlap(&host->pci.address_space_root,
                                           UINT64_C(0xa00000000),
                                           &s->pcie_ram_dma, -2);
    }
    if (s->pcie_image_ram_dma_input) {
        /* Same real RAM objects seen by CPU/ISP. Never copy pixels, expose
         * the whole system address space or fill the 512-byte bank gap.
         * Existing programmed inbound ATU and endpoint BARs retain priority. */
        DesignwarePCIEHost *host = DESIGNWARE_PCIE_HOST(dev);
        for (unsigned i = 0; i < ARRAY_SIZE(image_bank_ranges); i++) {
            g_autofree char *name = g_strdup_printf("z8.pcie-image-ram-%u", i);
            memory_region_init_alias(&s->pcie_image_ram_dma[i], OBJECT(s), name,
                &s->image_bank_ram[i], 0,
                image_bank_ranges[i].end - image_bank_ranges[i].base);
            memory_region_add_subregion_overlap(&host->pci.address_space_root,
                image_bank_ranges[i].base, &s->pcie_image_ram_dma[i], -2);
        }
    }
    memory_region_init_io(&s->pcie_dbi, OBJECT(s), &z8_pcie_dbi_ops, s,
                          "z8.pcie2-dbi", 0x1000);
    memory_region_add_subregion(mem, Z8_PCIE_DBI, &s->pcie_dbi);
    memory_region_init_io(&s->pcie_atu, OBJECT(s), &z8_pcie_atu_ops, s,
                          "z8.pcie2-unrolled-atu", 0x1000);
    memory_region_add_subregion(mem, Z8_PCIE_ATU, &s->pcie_atu);
    memory_region_init_io(&s->pcie_cpu_window, OBJECT(s), &z8_pcie_cpu_ops, s,
                          "z8.pcie2-cpu-window", UINT64_C(0x100000000));
    memory_region_add_subregion(mem, Z8_PCIE_CPU_WINDOW, &s->pcie_cpu_window);
}
