/* Copyright (C) 2026 RdWing: Z8/QEMU 11 adaptation.
 * Firmware addresses in inherited comments describe the Z6III donor.
 * STM32F4-compatible functional model; exact Z8 part/physical clock and
 * board-specific button/lens/shutter wiring require independent qualification. */
/*
 * Nikon Z 6III reference -- the body MCU, an STM32F469, running its own firmware.
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 *
 * The camera's external MCU (power, keys, battery, lens contacts, the
 * shoulder display, RTC -- see the object names in its image: PowMgCyc,
 * SwMngCyc, BatCmFlg, LnMngSem, DspTopPA, RtcMgEvF, ...) ships in the
 * firmware package as ex2010_0200a0.bi: a plain Cortex-M image, a 64 KiB
 * boot loader at 0x08000000 and the application at 0x08020000, vector
 * tables in the clear. Instead of answering the main CPU's frames from a
 * model of what the MCU would say (nikon-z8-mcu.h), this runs that image:
 * what it says is then its own.
 *
 * What has to be modelled is the chip, not the behaviour: a Cortex-M4 with
 * the STM32F469's memories and the peripherals the image uses, in an
 * address space of its own (the A53 cluster's map overlaps it everywhere).
 * The peripheral bases the image's literal pools name -- RCC 0x40023800,
 * FLASH 0x40023c00, GPIO 0x40020000 + 0x400 n, EXTI 0x40013c00, PWR
 * 0x40007000, RTC 0x40002800, TIM1/TIM8, USART1/6, SYSCFG, ADC1, DBGMCU --
 * are the F4 family's; the part is an STM32F469 (2 MiB flash, 320 KiB SRAM
 * plus 64 KiB CCM, over-drive for 180 MHz).
 *
 * Same discipline as the rest of the board: every register here is one the
 * reference manual (RM0386) defines and the image was seen to touch, and
 * any other access in the MCU's space stops the machine with the M4's PC.
 * (0x40013000 was once read as only an anchor for SYSCFG at [base + 0x808].
 * Both are real and both are in the image: 0x0804b8de does use the +0x808
 * form for SYSCFG_EXTICR1, and the trap that stops the image is at offset
 * 0, where it clears bit 6 -- CR1.SPE. See the SPI1 block below.)
 *
 * QEMU's own STM32F4 peripherals (USART, EXTI, SYSCFG, TIM2-5) are
 * added when the image reaches them; the stock stm32f405 SoC is not used
 * because it maps into the global address space and answers its many
 * unimplemented blocks with silent zeros.
 *
 * Declared simplifications, each visible in the code below:
 *  - clocks: SYSCLK is a fixed 180 MHz whatever RCC is programmed to; an
 *    oscillator or PLL reports ready as soon as it is enabled, and the
 *    switch status follows the switch request;
 *  - power: the regulator, over-drive and backup regulator report ready as
 *    soon as they are requested;
 *  - flash: sector/mass erase and programming act on the loaded image at
 *    once (no busy time); nothing is written back to the host file, so
 *    every run starts from the package's image;
 *  - GPIO inputs read their pull-up/pull-down level until something drives
 *    them (nothing does yet).
 */

#ifndef HW_ARM_NIKON_Z8_STM32_H
#define HW_ARM_NIKON_Z8_STM32_H

#include "hw/arm/armv7m.h"
#include "hw/cpu/cluster.h"
#include "hw/core/qdev-clock.h"
#include "migration/vmstate.h"
#include "hw/timer/stm32f2xx_timer.h"
#include "hw/core/or-irq.h"
#include "hw/misc/stm32f4xx_exti.h"
#include "hw/char/stm32f2xx_usart.h"
#include "chardev/char.h"
#include "system/rtc.h"
#include "system/reset.h"

#define Z8_STM32_FLASH_BASE    0x08000000ULL
#define Z8_STM32_FLASH_SIZE    (2 * MiB)
#define Z8_STM32_SRAM_BASE     0x20000000ULL
#define Z8_STM32_SRAM_SIZE     (320 * KiB)     /* SRAM1 160K + SRAM2 32K + SRAM3 128K */
#define Z8_STM32_CCM_BASE      0x10000000ULL
#define Z8_STM32_CCM_SIZE      (64 * KiB)
#define Z8_STM32_BKPSRAM_BASE  0x40024000ULL
#define Z8_STM32_BKPSRAM_SIZE  (4 * KiB)
#define Z8_STM32_SYSCLK_HZ     180000000ULL
#define Z8_STM32_NUM_IRQ       128             /* F4: up to 97 vectors past the core's */

#define Z8_STM32_RCC_BASE      0x40023800ULL
#define Z8_STM32_PWR_BASE      0x40007000ULL
#define Z8_STM32_FLASHIF_BASE  0x40023c00ULL
#define Z8_STM32_GPIO_BASE     0x40020000ULL
#define Z8_STM32_GPIO_PORTS    11              /* A..K */
#define Z8_STM32_SPI_N         6               /* SPI1..SPI6 */

typedef struct Z8Stm32 Z8Stm32;

typedef struct Z8Stm32Gpio {
    Z8Stm32 *mcu;
    unsigned port;
    MemoryRegion mr;
    uint32_t moder, otyper, ospeedr, pupdr, odr, lckr, afr[2];
    uint16_t driven, level;         /* inputs driven from outside */
    bool idr_named;
    unsigned odr_named;
    uint32_t idr_pcs[16];           /* readers named so far */
    unsigned idr_npcs;

} Z8Stm32Gpio;

/* One SPI instance. See the SPI block far below for what is and is not
 * modelled; this struct is up here only because Z8Stm32 embeds them. */
typedef struct Z8Stm32Spi {
    Z8Stm32 *mcu;
    unsigned inst;
    MemoryRegion mr;
    qemu_irq irq;
    uint32_t r[0x24 / 4];           /* CR1 CR2 SR DR CRCPR RXCRCR TXCRCR
                                     * I2SCFGR I2SPR (RM0386 28.5) */
    uint32_t seen;                  /* probe: one bit per register touched */
    uint32_t dr;                    /* last word handed back on a DR read */
    uint64_t words_out, words_in;   /* probe: DR writes / reads */
    unsigned enables;               /* CR1.SPE 0 -> 1, for the log */
    /* The peer on the other end of this bus, if one is wired up. A word
     * written to DR is handed to it and the word it returns is what the
     * next DR read sees -- which is what full duplex means. NULL is an
     * unconnected bus. See the board's mcu-spi-peer=. */
    uint16_t (*peer)(void *opaque, unsigned inst, uint16_t out);
    void *peer_opaque;
    /* A device that only listens -- no MISO -- if the board wired one:
     * every word shifted out is handed to it, and with CR2.TXDMAEN the
     * SPI fetches those words from the DMA itself, at its own bit rate
     * (z8_stm32_spi_tx_dma). The top LCD on SPI2 is one. */
    void (*sink)(void *opaque, unsigned inst, uint16_t out);
    void *sink_opaque;
    QEMUTimer *tx_timer;            /* the DMA words still on the wire */
    uint32_t tx_owed;               /* ... and how many */
} Z8Stm32Spi;

struct Z8Stm32 {
    MemoryRegion mem;               /* the MCU's own 4 GiB space */
    MemoryRegion flash, flash_alias, sram, ccm, bkpsram;
    MemoryRegion rcc_mr, pwr_mr, flashif_mr, trap;
    qemu_irq flash_irq;
    /* The M4 is a cluster of its own (cluster-id 1), as zynqmp does for its
     * R5s: QEMU's gdbstub then shows it as a second inferior (process 2)
     * beside the A53s, so it can be stopped, stepped and walked by itself,
     * and TCG never shares a translation between the two. */
    CPUClusterState cluster;
    ARMv7MState armv7m;
    qemu_irq sysresetreq;
    bool system_reset_pending;
    uint64_t system_resets;
    Clock *sysclk, *refclk;
    QEMUTimer *dbg_timer;           /* TEMPORARY PROBE (remove) */

    /* Whatever the board wired to a DMA stream: called when one is armed,
     * and by z8_stm32_dma_kick(). The chip knows nothing about it. */
    void (*link_kick)(void *opaque);
    void *link_kick_opaque;

    /* Also the board's: called when an output pin's level changes, which is
     * an edge on whatever the other chip wired to it. The chip does not
     * know what that is either. */
    void (*pin_out)(void *opaque, unsigned port, unsigned pin, bool level);
    void *pin_out_opaque;

    uint32_t rcc[0x98 / 4];
    uint32_t pwr_cr, pwr_csr;
    bool stop_active, stop_wfe, stop_systick_run;
    uint64_t stop_entries, stop_wakes;
    int64_t stop_enter_ns;
    int64_t stop_spi_deadline[Z8_STM32_SPI_N];
    qemu_irq exti_irq[23], exti_event;
    uint32_t flash_acr, flash_cr, flash_sr, flash_optcr, flash_optcr1;
    unsigned flash_key;
    bool flash_ignored_named;           /* the not-programming-mode write */

    Z8Stm32Gpio gpio[Z8_STM32_GPIO_PORTS];
    STM32F2XXTimerState tim[4];         /* TIM2..TIM5, QEMU's model */
    STM32F2XXTimerState tim_more[10];   /* TIM1, 8, 9-14, 6, 7 */
    OrIRQState tim_or[2];               /* vectors 25 and 44 are shared */
    STM32F2XXUsartState usart[6];       /* USART1-3, UART4-5, USART6 */
    STM32F4xxExtiState exti;            /* GPIO 0..15 and internal 16..22 */
    struct {                            /* z8_stm32_shutter_tick */
        QEMUTimer *timer;
        uint8_t pos;                    /* 0..3, the table at 0x8058670 */
        int8_t dir;                     /* +1 forward, -1 reverse, 0 */
        int64_t driven_ns;              /* drive since the last step */
        uint64_t steps;
        unsigned named;
    } shutter;
    MemoryRegion syscfg_mr;
    uint32_t syscfg[0x30 / 4];          /* MEMRMP PMC EXTICR1-4 .. CMPCR, +0x24.. */
    Z8Stm32Spi spi[Z8_STM32_SPI_N];

    struct Z8Stm32I2cDev {
        uint8_t bus, addr;              /* bus 0..2 = I2C1..3, 3 = FMPI2C1 */
        uint8_t regs[256], ptr;
        bool ptr_set;
        uint64_t writes, reads;
        /* The two button expanders (below z8_stm32_i2c_dev_at): input
         * levels, 1 = released; logged, the last levels reported. */
        bool expander;
        uint32_t inputs, logged;
        /* The clock chip at I2C1 0x32 (below z8_stm32_i2c_dev_at). */
        bool clock;
        int64_t clock_base_s;           /* seconds since 2000 at epoch */
        int64_t clock_epoch_ns;
    } i2c_dev[6];

    struct Z8Stm32I2c {
        Z8Stm32 *mcu;
        unsigned bus;
        struct Z8Stm32I2cDev *dev;
        bool last_sent;                 /* the NACKed byte has come */
        uint8_t sh;                     /* the shift register's byte */
        bool sh_full;
        MemoryRegion mr;
        qemu_irq ev_irq, er_irq;
        uint32_t cr1, cr2, oar1, oar2, ccr, trise, fltr;
        uint32_t sr1, sr2;
        uint8_t dr, addr;
        bool sb_seen, addr_seen, selected, reading;
        uint8_t nack_named[128 / 8];
    } i2c[3];

    struct {
        MemoryRegion mr;
        qemu_irq ev_irq, er_irq;
        uint32_t cr1, cr2, oar1, oar2, timingr, timeoutr, isr;
        struct Z8Stm32I2cDev *dev;
        unsigned left;
        uint8_t rxdr;
        uint8_t nack_named[128 / 8];
    } fmpi2c;

    struct Z8Stm32Dma {
        Z8Stm32 *mcu;
        unsigned ctrl;
        MemoryRegion mr;
        uint32_t isr[2];                /* LISR, HISR */
        struct {
            uint32_t cr, ndtr, par, m0ar, m1ar, fcr;
            uint32_t cur_m, cur_p, ndtr_init;   /* latched at enable */
            qemu_irq irq;
            bool named;
        } s[8];
    } dma[2];

    struct {
        MemoryRegion mr;
        qemu_irq irq;
        uint32_t r[3][0x50 / 4];        /* ADC1..3 register files */
        uint32_t ccr;
        uint16_t input[3][19];          /* declared channel levels */
        bool dma_named;
    } adc;

    MemoryRegion rtc_mr;
    uint32_t rtc[0xa0 / 4];
    int64_t rtc_base_s;             /* calendar seconds at rtc_epoch_ns */
    int64_t rtc_epoch_ns;
    unsigned rtc_wpr;               /* 0, 1 (0xca seen), 2 (unlocked) */
    bool rtc_named_timer;
    QEMUTimer *rtc_alarm_timer, *rtc_wake_timer;
    bool rtc_alarm_level, rtc_wake_level;
    uint64_t rtc_alarm_events[2], rtc_wake_events;
    int64_t rtc_wake_deadline;
    bool rtc_running;               /* mcu-rtc=: the calendar kept time */
    int64_t rtc_start_s;            /* ... and read this at power-on */
};

/* TIM2..5: general-purpose 32/16-bit timers, QEMU's stm32f2xx model.
 * Their kernel clock on this part: APB1 at 45 MHz, timers x2 = 90 MHz
 * (the image sets APB1 = HCLK / 4). The application reads TIM5 first
 * (pc 0x080522ca). */
static const hwaddr z8_stm32_tim_base[4] = {
    0x40000000, 0x40000400, 0x40000800, 0x40000c00,
};
static const int z8_stm32_tim_irq[4] = { 28, 29, 30, 50 };
#define Z8_STM32_TIM_HZ 90000000

/* The other timers, QEMU's general-purpose model for each (the advanced
 * TIM1/TIM8 extras -- RCR, BDTR, complementary outputs -- are not
 * modelled). APB2 timers run at 180 MHz, APB1 ones at 90 MHz. irq < 0
 * names a shared vector: -1 is 25 (TIM1_UP/TIM10), -2 is 44 (TIM8_UP/
 * TIM13). The application reads TIM11 at pc 0x080522ca. cc is TIM1's and
 * TIM8's separate capture/compare vector (27, 46): the SbCtl task's 5000-
 * tick transfer timeout is a TIM1 channel 2 match, which on the update
 * vector reached nobody. */
static const struct {
    const char *name;
    hwaddr base;
    int irq;
    uint64_t hz;
    int cc;
} z8_stm32_tim_more[10] = {
    { "tim1",  0x40010000, -1, 180000000, 27 },
    { "tim8",  0x40010400, -2, 180000000, 46 },
    { "tim9",  0x40014000, 24, 180000000 },
    { "tim10", 0x40014400, -1, 180000000 },
    { "tim11", 0x40014800, 26, 180000000 },
    { "tim12", 0x40001800, 43, 90000000 },
    { "tim13", 0x40001c00, -2, 90000000 },
    { "tim14", 0x40002000, 45, 90000000 },
    { "tim6",  0x40001000, 54, 90000000 },
    { "tim7",  0x40001400, 55, 90000000 },
};

/* DMA requests from a peripheral whose data register is at `par`: give it
 * the next item (memory to peripheral) or take one (peripheral to memory).
 * False when no enabled stream serves it. Defined with the DMA model. */
static bool z8_stm32_dma_tx(Z8Stm32 *m, uint32_t par, uint32_t *value);
static bool z8_stm32_dma_rx(Z8Stm32 *m, uint32_t par, uint32_t value);
static void z8_stm32_dma_kick(Z8Stm32 *m);
static void z8_stm32_stop_clocks(Z8Stm32 *m, bool stopped);
static uint32_t z8_stm32_dma_left(Z8Stm32 *m, uint32_t par, bool to_periph);

static uint32_t z8_stm32_pc(void)
{
    return current_cpu ? ARM_CPU(current_cpu)->env.regs[15] : 0;
}

static void z8_stm32_stop(const char *block, hwaddr addr, unsigned size,
                         bool write, uint64_t value)
{
    if (write) {
        error_report("Z8_STM32 %s unmodeled write addr=0x%08" HWADDR_PRIx
                     " size=%u value=0x%" PRIx64 " pc=0x%08x -- stopping",
                     block, addr, size, value, z8_stm32_pc());
    } else {
        error_report("Z8_STM32 %s unmodeled read  addr=0x%08" HWADDR_PRIx
                     " size=%u pc=0x%08x -- stopping",
                     block, addr, size, z8_stm32_pc());
    }
    qemu_system_shutdown_request_with_code(SHUTDOWN_CAUSE_GUEST_PANIC, 3);
}

/* ------------------------------------------------------------------ */
/* Everything the image was not seen to need.                          */
/* ------------------------------------------------------------------ */

static uint64_t z8_stm32_trap_read(void *opaque, hwaddr addr, unsigned size)
{
    z8_stm32_stop("space", addr, size, false, 0);
    return 0;
}

static void z8_stm32_trap_write(void *opaque, hwaddr addr, uint64_t value,
                               unsigned size)
{
    z8_stm32_stop("space", addr, size, true, value);
}

static const MemoryRegionOps z8_stm32_trap_ops = {
    .read = z8_stm32_trap_read,
    .write = z8_stm32_trap_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4 },
};

/* ------------------------------------------------------------------ */
/* RCC (RM0386 section 6). Ready bits follow their enables.            */
/* ------------------------------------------------------------------ */

#define Z8_RCC_CR        0x00
#define Z8_RCC_CFGR      0x08
#define Z8_RCC_CIR       0x0c
#define Z8_RCC_BDCR      0x70
#define Z8_RCC_CSR       0x74

static bool z8_stm32_rcc_valid(hwaddr off)
{
    switch (off) {
    case 0x00: case 0x04: case 0x08: case 0x0c:     /* CR PLLCFGR CFGR CIR */
    case 0x10: case 0x14: case 0x18:                /* AHB1-3 RSTR */
    case 0x20: case 0x24:                           /* APB1-2 RSTR */
    case 0x30: case 0x34: case 0x38:                /* AHB1-3 ENR */
    case 0x40: case 0x44:                           /* APB1-2 ENR */
    case 0x50: case 0x54: case 0x58:                /* AHB1-3 LPENR */
    case 0x60: case 0x64:                           /* APB1-2 LPENR */
    case 0x70: case 0x74:                           /* BDCR CSR */
    case 0x80: case 0x84: case 0x88: case 0x8c:     /* SSCGR PLLI2S PLLSAI DCKCFGR */
        return true;
    case 0x90: case 0x94:
        /* CKGATENR/DCKCFGR2 on the F412/F413/F446; the boot loader
         * read-modify-writes 0x94 (pc 0x080007a2). Storage. */
        return true;
    }
    return false;
}

static void z8_stm32_rcc_reset(Z8Stm32 *m)
{
    memset(m->rcc, 0, sizeof(m->rcc));
    m->rcc[0x00 / 4] = 0x00000083;  /* HSION, HSIRDY, HSITRIM 16 */
    m->rcc[0x04 / 4] = 0x24003010;
    m->rcc[0x30 / 4] = 0x00100000;
    m->rcc[0x50 / 4] = 0x7e6791ff;
    m->rcc[0x54 / 4] = 0x000000f1;
    m->rcc[0x58 / 4] = 0x00000003;
    m->rcc[0x60 / 4] = 0xf6fec9ff;
    m->rcc[0x64 / 4] = 0x0c777f33;
    m->rcc[0x74 / 4] = 0x0e000000;  /* PORRSTF PINRSTF BORRSTF: a power-on */
    m->rcc[0x84 / 4] = 0x24003000;
    m->rcc[0x88 / 4] = 0x24003000;
}

static uint64_t z8_stm32_rcc_read(void *opaque, hwaddr off, unsigned size)
{
    Z8Stm32 *m = opaque;
    uint32_t v;

    if (size != 4 || !z8_stm32_rcc_valid(off)) {
        z8_stm32_stop("RCC", Z8_STM32_RCC_BASE + off, size, false, 0);
        return 0;
    }
    v = m->rcc[off / 4];
    switch (off) {
    case Z8_RCC_CR:
        v &= ~((1u << 1) | (1u << 17) | (1u << 25) | (1u << 27) | (1u << 29));
        v |= (v & 1u) << 1;                 /* HSIRDY    <- HSION */
        v |= (v & (1u << 16)) << 1;         /* HSERDY    <- HSEON */
        v |= (v & (1u << 24)) << 1;         /* PLLRDY    <- PLLON */
        v |= (v & (1u << 26)) << 1;         /* PLLI2SRDY <- PLLI2SON */
        v |= (v & (1u << 28)) << 1;         /* PLLSAIRDY <- PLLSAION */
        break;
    case Z8_RCC_CFGR:
        v = (v & ~0xcu) | ((v & 3u) << 2);  /* SWS <- SW */
        break;
    case Z8_RCC_BDCR:
        v = (v & ~2u) | ((v & 1u) << 1);    /* LSERDY <- LSEON */
        break;
    case Z8_RCC_CSR:
        v = (v & ~2u) | ((v & 1u) << 1);    /* LSIRDY <- LSION */
        break;
    }
    return v;
}

static void z8_stm32_rtc_reclock(Z8Stm32 *m);

static void z8_stm32_rcc_write(void *opaque, hwaddr off, uint64_t value,
                              unsigned size)
{
    Z8Stm32 *m = opaque;

    if (size != 4 || !z8_stm32_rcc_valid(off)) {
        z8_stm32_stop("RCC", Z8_STM32_RCC_BASE + off, size, true, value);
        return;
    }
    switch (off) {
    case Z8_RCC_CIR:
        /* No ready interrupt is ever raised: keep the enables, the clear
         * bits (16..23) have nothing to clear. */
        m->rcc[off / 4] = value & 0x00007f00;
        return;
    case Z8_RCC_CSR:
        if (value & (1u << 24)) {           /* RMVF clears the reset flags */
            m->rcc[off / 4] &= 0x00ffffff;
        }
        m->rcc[off / 4] = (m->rcc[off / 4] & 0xfe000000) | (value & 1u);
        return;
    }
    m->rcc[off / 4] = value;
    if (off == Z8_RCC_BDCR && m->rtc_alarm_timer) {
        z8_stm32_rtc_reclock(m);
    }
}

static const MemoryRegionOps z8_stm32_rcc_ops = {
    .read = z8_stm32_rcc_read,
    .write = z8_stm32_rcc_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4 },
};

/* ------------------------------------------------------------------ */
/* PWR (RM0386 section 5): regulator, over-drive, backup regulator.    */
/* ------------------------------------------------------------------ */

static uint64_t z8_stm32_pwr_read(void *opaque, hwaddr off, unsigned size)
{
    Z8Stm32 *m = opaque;
    uint32_t v;

    if (size != 4 || off > 0x04) {
        z8_stm32_stop("PWR", Z8_STM32_PWR_BASE + off, size, false, 0);
        return 0;
    }
    if (off == 0x00) {
        return m->pwr_cr;
    }
    v = m->pwr_csr & ((1u << 8) | (1u << 9));          /* EWUP, BRE */
    v |= (v & (1u << 9)) ? (1u << 3) : 0;               /* BRR <- BRE */
    v |= 1u << 14;                                      /* VOSRDY */
    v |= (m->pwr_cr & (1u << 16)) ? (1u << 16) : 0;     /* ODRDY <- ODEN */
    v |= (m->pwr_cr & (1u << 17)) ? (1u << 17) : 0;     /* ODSWRDY <- ODSWEN */
    return v;
}

static void z8_stm32_pwr_write(void *opaque, hwaddr off, uint64_t value,
                              unsigned size)
{
    Z8Stm32 *m = opaque;

    if (size != 4 || off > 0x04) {
        z8_stm32_stop("PWR", Z8_STM32_PWR_BASE + off, size, true, value);
        return;
    }
    if (off == 0x00) {
        m->pwr_cr = value & ~((1u << 2) | (1u << 3));   /* CWUF/CSBF: clear */
    } else {
        m->pwr_csr = value & ((1u << 8) | (1u << 9));
    }
}

static const MemoryRegionOps z8_stm32_pwr_ops = {
    .read = z8_stm32_pwr_read,
    .write = z8_stm32_pwr_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4 },
};

/* ------------------------------------------------------------------ */
/* FLASH interface (RM0386 section 3.9): latency, caches, the lock.    */
/* ------------------------------------------------------------------ */

/* Sector n of a bank: 4 x 16K, 64K, 7 x 128K (RM0386 3.4); SNB bit 4
 * selects bank 2, 1 MiB up. */
static void z8_stm32_flash_sector(unsigned snb, hwaddr *base, uint32_t *len)
{
    unsigned idx = snb & 0xf;

    if (idx < 4) {
        *base = idx * 16 * KiB;
        *len = 16 * KiB;
    } else if (idx == 4) {
        *base = 64 * KiB;
        *len = 64 * KiB;
    } else {
        *base = (idx - 4) * 128 * KiB;
        *len = 128 * KiB;
    }
    *base += (snb & 0x10) ? MiB : 0;
}

static void z8_stm32_flash_erase(Z8Stm32 *m, hwaddr base, uint32_t len)
{
    uint8_t *p = memory_region_get_ram_ptr(&m->flash);

    if (base + len > Z8_STM32_FLASH_SIZE) {
        z8_stm32_stop("FLASH erase", Z8_STM32_FLASH_BASE + base, 4, true,
                       len);
        return;
    }
    memset(p + base, 0xff, len);
    memory_region_flush_rom_device(&m->flash, base, len);
    error_report("Z8_STM32: flash erased 0x%08" HWADDR_PRIx "..+0x%x "
                 "(pc=0x%08x)", Z8_STM32_FLASH_BASE + base, len,
                 z8_stm32_pc());
}

static void z8_stm32_flash_done(Z8Stm32 *m)
{
    if (m->flash_cr & (1u << 24)) {             /* EOPIE */
        m->flash_sr |= 1;                       /* EOP */
    }
    qemu_set_irq(m->flash_irq, (m->flash_sr & 1) && (m->flash_cr & (1u << 24)));
}

static uint64_t z8_stm32_flashif_read(void *opaque, hwaddr off, unsigned size)
{
    Z8Stm32 *m = opaque;

    if (size == 1 && off == 0x00) {     /* ACR byte 0: LATENCY (HAL style) */
        return m->flash_acr & 0xff;
    }
    if (size == 4) {
        switch (off) {
        case 0x00: return m->flash_acr;
        case 0x0c: return m->flash_sr;
        case 0x10: return m->flash_cr;
        case 0x14: return m->flash_optcr;
        case 0x18: return m->flash_optcr1;
        }
    }
    z8_stm32_stop("FLASH", Z8_STM32_FLASHIF_BASE + off, size, false, 0);
    return 0;
}

static void z8_stm32_flashif_write(void *opaque, hwaddr off, uint64_t value,
                                  unsigned size)
{
    Z8Stm32 *m = opaque;

    if (size == 1 && off == 0x00) {     /* ACR byte 0: LATENCY (HAL style) */
        m->flash_acr = (m->flash_acr & ~0xffu) | (value & 0x0f);
        return;
    }
    if (size == 4) {
        switch (off) {
        case 0x00:
            m->flash_acr = value & ~((1u << 11) | (1u << 12)); /* ICRST/DCRST */
            return;
        case 0x04:                                  /* KEYR */
            if (m->flash_key == 0 && value == 0x45670123) {
                m->flash_key = 1;
            } else if (m->flash_key == 1 && value == 0xcdef89ab) {
                m->flash_cr &= ~(1u << 31);
                m->flash_key = 0;
            } else {
                m->flash_key = 0;       /* a wrong key: CR stays locked */
            }
            return;
        case 0x0c:                                  /* SR: W1C */
            m->flash_sr &= ~(value & 0x1f3);
            qemu_set_irq(m->flash_irq,
                         (m->flash_sr & 1) && (m->flash_cr & (1u << 24)));
            return;
        case 0x10:
            if (value & (1u << 31)) {
                m->flash_cr = 1u << 31;
                return;
            }
            if (m->flash_cr & (1u << 31)) {
                return;                 /* locked: ignored, as on the part */
            }
            m->flash_cr = value & ~(1u << 16);
            if (value & (1u << 16)) {   /* STRT */
                if (value & ((1u << 2) | (1u << 15))) {        /* MER MER1 */
                    if (value & (1u << 2)) {
                        z8_stm32_flash_erase(m, 0, MiB);
                    }
                    if (value & (1u << 15)) {
                        z8_stm32_flash_erase(m, MiB, MiB);
                    }
                } else if (value & (1u << 1)) {                 /* SER */
                    hwaddr base;
                    uint32_t len;

                    z8_stm32_flash_sector((value >> 3) & 0x1f, &base, &len);
                    z8_stm32_flash_erase(m, base, len);
                } else {
                    break;
                }
                z8_stm32_flash_done(m);
            }
            return;
        }
    }
    z8_stm32_stop("FLASH", Z8_STM32_FLASHIF_BASE + off, size, true, value);
}

static const MemoryRegionOps z8_stm32_flashif_ops = {
    .read = z8_stm32_flashif_read,
    .write = z8_stm32_flashif_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4 },
};

/* Writes to the flash array itself are programming: with CR.PG set and
 * the interface unlocked, bits go from 1 to 0 (new & old). Anything else
 * is a programming error on the part, and stops here. */
static void z8_stm32_flash_write(void *opaque, hwaddr off, uint64_t value,
                                  unsigned size)
{
    Z8Stm32 *m = opaque;
    uint8_t *p = memory_region_get_ram_ptr(&m->flash);

    if ((m->flash_cr & (1u << 31)) || !(m->flash_cr & 1)) {
        /*
         * Not locked-and-programming-enabled: the part ignores the write
         * (RM0386 3.9.2 -- no bus fault, the word is simply discarded), and
         * so does this. It used to stop here, on the theory that any write
         * outside programming mode means the model's flash controller had
         * drifted; it does not. The image reaches this path at pc
         * 0x08052340, a HAL_TIM_Base_Init whose handle carries a garbage
         * Instance (0x08020369, unaligned and inside the default-handler
         * stubs), so its register writes land in flash. On the part that
         * is a silent no-op and the firmware carries on. Named once, so a
         * real divergence is still visible rather than buried.
         */
        if (!m->flash_ignored_named) {
            m->flash_ignored_named = true;
            error_report("Z8_STM32: write to flash at 0x%" HWADDR_PRIx
                         " with the controller not in programming mode "
                         "(CR=0x%08x) -- ignored, as on the part; pc=0x%08x",
                         Z8_STM32_FLASH_BASE + off, m->flash_cr,
                         z8_stm32_pc());
        }
        return;
    }
    for (unsigned i = 0; i < size; i++) {
        p[off + i] &= value >> (8 * i);
    }
    memory_region_flush_rom_device(&m->flash, off, size);
    z8_stm32_flash_done(m);
}

static const MemoryRegionOps z8_stm32_flash_ops = {
    .write = z8_stm32_flash_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4 },
};

/* ------------------------------------------------------------------ */
/* GPIO A..K (RM0386 section 8).                                       */
/* ------------------------------------------------------------------ */

static uint16_t z8_stm32_gpio_idr(Z8Stm32Gpio *g)
{
    uint16_t v = 0;

    for (unsigned pin = 0; pin < 16; pin++) {
        unsigned mode = (g->moder >> (2 * pin)) & 3;
        unsigned pull = (g->pupdr >> (2 * pin)) & 3;
        bool level;

        if (mode == 1) {
            level = g->odr & (1u << pin);           /* output: reads back */
        } else if (g->driven & (1u << pin)) {
            level = g->level & (1u << pin);
        } else {
            level = pull == 1;                      /* pull-up reads 1 */
        }
        v |= level << pin;
    }
    return v;
}

/* Drive an input from outside (a switch, a peer's handshake line). An
 * input whose level changes reaches EXTI through SYSCFG's routing, as on
 * the part. */
static void z8_stm32_gpio_drive(Z8Stm32Gpio *g, unsigned pin, bool level)
{
    uint16_t before = z8_stm32_gpio_idr(g);
    uint16_t after;

    g->driven |= 1u << pin;
    g->level = (g->level & ~(1u << pin)) | (level << pin);
    after = z8_stm32_gpio_idr(g);
    if (((before ^ after) >> pin) & 1 &&
        ((g->mcu->syscfg[(0x08 + 4 * (pin / 4)) / 4] >> (4 * (pin % 4))) & 0xf)
        == g->port) {
        qemu_set_irq(qdev_get_gpio_in(DEVICE(&g->mcu->exti), pin), level);
    }
}

/* Press (active) or release one input of a button expander (addr 0x22 or
 * 0x23, bit 0..23); the MCU sees it at its next poll. */
static bool z8_stm32_expander_set(Z8Stm32 *m, uint8_t addr, unsigned bit,
                                   bool active)
{
    for (unsigned i = 0; i < ARRAY_SIZE(m->i2c_dev); i++) {
        struct Z8Stm32I2cDev *d = &m->i2c_dev[i];
        uint32_t was;

        if (!d->expander || d->addr != addr || bit > 23) {
            continue;
        }
        was = d->inputs;
        d->inputs = active ? was & ~(1u << bit) : was | (1u << bit);
        return true;
    }
    return false;
}

/* "G7=1,C5=0": drive those inputs. */
static bool z8_stm32_pins(Z8Stm32 *m, const char *spec, Error **errp)
{
    g_auto(GStrv) items = g_strsplit_set(spec ? spec : "", ",:", -1);

    for (char **it = items; *it; it++) {
        unsigned port, pin, level;
        char c;

        if (!**it) {
            continue;
        }
        if (sscanf(*it, "%c%u=%u", &c, &pin, &level) != 3 ||
            (c = g_ascii_toupper(c)) < 'A' || c > 'K' || pin > 15 ||
            level > 1) {
            error_setg(errp, "pins: '%s' is not <port><pin>=<0|1>", *it);
            return false;
        }
        port = c - 'A';
        z8_stm32_gpio_drive(&m->gpio[port], pin, level);
        error_report("Z8_STM32: P%c%u driven %u", c, pin, level);
    }
    return true;
}

static uint64_t z8_stm32_gpio_read(void *opaque, hwaddr off, unsigned size)
{
    Z8Stm32Gpio *g = opaque;

    if (size == 4) {
        switch (off) {
        case 0x00: return g->moder;
        case 0x04: return g->otyper;
        case 0x08: return g->ospeedr;
        case 0x0c: return g->pupdr;
        case 0x10:
        {
            uint32_t pc = z8_stm32_pc();
            unsigned i;

            /* Name each reader once (up to 16 a port): which code polls
             * which port is how the switches and status lines are found. */
            for (i = 0; i < g->idr_npcs && g->idr_pcs[i] != pc; i++) {
            }
            if (i == g->idr_npcs && i < ARRAY_SIZE(g->idr_pcs)) {
                g->idr_pcs[g->idr_npcs++] = pc;
                error_report("Z8_STM32: GPIO%c inputs read at pc=0x%08x "
                             "(lr=0x%08x): 0x%04x, moder 0x%08x pupdr 0x%08x",
                             'A' + g->port, pc,
                             current_cpu ? ARM_CPU(current_cpu)->env.regs[14]
                                         : 0,
                             z8_stm32_gpio_idr(g), g->moder, g->pupdr);
            }
            return z8_stm32_gpio_idr(g);
        }
        case 0x14: return g->odr;
        case 0x1c: return g->lckr;
        case 0x20: return g->afr[0];
        case 0x24: return g->afr[1];
        }
    }
    z8_stm32_stop("GPIO", Z8_STM32_GPIO_BASE + 0x400 * g->port + off, size,
                 false, 0);
    return 0;
}

static void z8_stm32_gpio_set_odr(Z8Stm32Gpio *g, uint32_t odr)
{
    odr &= 0xffff;
    if (odr != g->odr && g->odr_named < 64) {
        g->odr_named++;
        /* TEMPORARY PROBE (remove): every pin write goes through one HAL
         * function, so the PC alone does not say who drove the pin; the
         * return address does. */
        uint32_t lr = getenv("Z8_STM32_DEBUG") ?
            (uint32_t)g->mcu->armv7m.cpu->env.regs[14] : 0;

        error_report("Z8_STM32: GPIO%c outputs 0x%04x -> 0x%04x "
                     "(pc=0x%08x lr=0x%08x)",
                     'A' + g->port, g->odr, odr, z8_stm32_pc(), lr);
    }
    if (g->mcu->pin_out && g->odr != odr) {
        uint16_t changed = g->odr ^ odr;

        for (unsigned pin = 0; pin < 16; pin++) {
            if (changed & (1u << pin)) {
                g->mcu->pin_out(g->mcu->pin_out_opaque, g->port, pin,
                                (odr >> pin) & 1);
            }
        }
    }
    g->odr = odr;
}

static void z8_stm32_gpio_write(void *opaque, hwaddr off, uint64_t value,
                               unsigned size)
{
    Z8Stm32Gpio *g = opaque;

    if (size == 4) {
        switch (off) {
        case 0x00: g->moder = value; return;
        case 0x04: g->otyper = value & 0xffff; return;
        case 0x08: g->ospeedr = value; return;
        case 0x0c: g->pupdr = value; return;
        case 0x14: z8_stm32_gpio_set_odr(g, value); return;
        case 0x18:                                  /* BSRR: reset wins */
            z8_stm32_gpio_set_odr(g, (g->odr | (value & 0xffff)) &
                                    ~(value >> 16));
            return;
        case 0x1c: g->lckr = value & 0x1ffff; return;
        case 0x20: g->afr[0] = value; return;
        case 0x24: g->afr[1] = value; return;
        }
    }
    z8_stm32_stop("GPIO", Z8_STM32_GPIO_BASE + 0x400 * g->port + off, size,
                 true, value);
}

static const MemoryRegionOps z8_stm32_gpio_ops = {
    .read = z8_stm32_gpio_read,
    .write = z8_stm32_gpio_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4 },
};

static void z8_stm32_gpio_reset(Z8Stm32Gpio *g)
{
    g->moder = g->otyper = g->ospeedr = g->pupdr = 0;
    g->odr = g->lckr = g->afr[0] = g->afr[1] = 0;
    if (g->port == 0) {                 /* PA13/14/15: SWD/JTAG */
        g->moder = 0xa8000000;
        g->ospeedr = 0x0c000000;
        g->pupdr = 0x64000000;
    } else if (g->port == 1) {          /* PB3/4: JTAG */
        g->moder = 0x00000280;
        g->ospeedr = 0x000000c0;
        g->pupdr = 0x00000100;
    }
}

/* ------------------------------------------------------------------ */
/* RTC (RM0386 section 25): the camera's clock.                        */
/* ------------------------------------------------------------------ */
/*
 * The calendar runs on QEMU's virtual clock from the value the firmware
 * last wrote in initialisation mode (RM0386 25.3.5: set INIT, wait INITF,
 * write TR/DR, clear INIT). Shadow registers are always synchronised (RSF
 * reads 1). LSE-backed alarm comparisons and periodic wakeup now raise
 * their original flags/EXTI inputs. Timestamp, tamper and calibration remain
 * storage without events. Backup registers
 * BKP0R..BKP19R are storage.
 */
#define Z8_STM32_RTC_BASE 0x40002800ULL
#define Z8_RTC_TR   0x00
#define Z8_RTC_DR   0x04
#define Z8_RTC_CR   0x08
#define Z8_RTC_ISR  0x0c
#define Z8_RTC_WPR  0x24
#define Z8_RTC_SSR  0x28

static unsigned z8_bcd(unsigned v) { return (v / 10) << 4 | (v % 10); }
static unsigned z8_unbcd(unsigned v) { return (v >> 4) * 10 + (v & 15); }

/* TR/DR (BCD, 24-hour) <-> seconds since 2000-01-01, the RTC's century. */
static int64_t z8_stm32_rtc_to_s(uint32_t tr, uint32_t dr)
{
    struct tm t = {
        .tm_year = 100 + z8_unbcd((dr >> 16) & 0xff),
        .tm_mon = z8_unbcd((dr >> 8) & 0x1f) - 1,
        .tm_mday = z8_unbcd(dr & 0x3f),
        .tm_hour = z8_unbcd((tr >> 16) & 0x3f),
        .tm_min = z8_unbcd((tr >> 8) & 0x7f),
        .tm_sec = z8_unbcd(tr & 0x7f),
    };

    if (t.tm_mon < 0) {
        t.tm_mon = 0;
    }
    if (t.tm_mday == 0) {
        t.tm_mday = 1;
    }
    return mktimegm(&t) - 946684800;
}

static void z8_stm32_rtc_from_s(int64_t s, uint32_t *tr, uint32_t *dr)
{
    time_t tt = s + 946684800;
    struct tm t;

    gmtime_r(&tt, &t);
    *tr = z8_bcd(t.tm_hour) << 16 | z8_bcd(t.tm_min) << 8 | z8_bcd(t.tm_sec);
    *dr = z8_bcd(t.tm_year - 100) << 16 | (t.tm_wday ? t.tm_wday : 7) << 13 |
          z8_bcd(t.tm_mon + 1) << 8 | z8_bcd(t.tm_mday);
}

static int64_t z8_stm32_rtc_now_s(Z8Stm32 *m)
{
    return m->rtc_base_s + (qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) -
                            m->rtc_epoch_ns) / NANOSECONDS_PER_SECOND;
}

/* Calendar fixture: one second of virtual time, LSE 32768 Hz. Alarm
 * comparisons follow PREDIV_S within that second. Other RTC clock sources
 * remain unsupported for event generation rather than inventing a rate. */
static bool z8_stm32_rtc_clocked(Z8Stm32 *m)
{
    uint32_t bdcr = m->rcc[Z8_RCC_BDCR / 4];
    return (bdcr & 0x8301) == 0x8101 &&
           !(m->rtc[Z8_RTC_ISR / 4] & (1u << 7));
}

static unsigned z8_stm32_rtc_ss(Z8Stm32 *m)
{
    unsigned prediv = m->rtc[0x10 / 4] & 0x7fff;
    if (m->rtc[Z8_RTC_ISR / 4] & (1u << 7)) {
        return prediv;
    }
    int64_t elapsed = MAX(0, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) - m->rtc_epoch_ns);
    return prediv - (elapsed % NANOSECONDS_PER_SECOND) * (prediv + 1) /
                     NANOSECONDS_PER_SECOND;
}

static void z8_stm32_rtc_irq(Z8Stm32 *m)
{
    uint32_t cr = m->rtc[Z8_RTC_CR / 4], isr = m->rtc[Z8_RTC_ISR / 4];
    bool alarm = (isr & ((cr >> 4) & 0x300)) != 0;
    bool wake = (isr & ((cr >> 4) & 0x400)) != 0;
    if (alarm != m->rtc_alarm_level) {
        m->rtc_alarm_level = alarm;
        qemu_set_irq(qdev_get_gpio_in(DEVICE(&m->exti), 17), alarm);
    }
    if (wake != m->rtc_wake_level) {
        m->rtc_wake_level = wake;
        qemu_set_irq(qdev_get_gpio_in(DEVICE(&m->exti), 22), wake);
    }
}

static int64_t z8_stm32_rtc_wake_period(Z8Stm32 *m)
{
    unsigned select = m->rtc[Z8_RTC_CR / 4] & 7;
    uint64_t ticks = (m->rtc[0x14 / 4] & 0xffff) + 1;
    if (select < 4) {
        ticks *= 16 >> select;
    } else {
        ticks += select & 2 ? 65536 : 0;
        ticks *= (((m->rtc[0x10 / 4] >> 16) & 127) + 1) *
                 ((m->rtc[0x10 / 4] & 32767) + 1);
    }
    /* Round only the fractional nanosecond upward, without overflowing. */
    return ticks / 32768 * NANOSECONDS_PER_SECOND +
           ((ticks % 32768) * NANOSECONDS_PER_SECOND + 32767) / 32768;
}

static void z8_stm32_rtc_alarm_schedule(Z8Stm32 *m)
{
    timer_del(m->rtc_alarm_timer);
    if (z8_stm32_rtc_clocked(m) && (m->rtc[Z8_RTC_CR / 4] & 0x300)) {
        int64_t now = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
        int64_t elapsed = MAX(0, now - m->rtc_epoch_ns);
        unsigned n = (m->rtc[0x10 / 4] & 32767) + 1;
        int64_t phase = elapsed % NANOSECONDS_PER_SECOND;
        uint64_t next = phase * n / NANOSECONDS_PER_SECOND + 1;
        timer_mod(m->rtc_alarm_timer, m->rtc_epoch_ns +
                  elapsed / NANOSECONDS_PER_SECOND * NANOSECONDS_PER_SECOND +
                  (next * NANOSECONDS_PER_SECOND + n - 1) / n);
    }
}

static void z8_stm32_rtc_wake_arm(Z8Stm32 *m, int64_t deadline)
{
    m->rtc_wake_deadline = deadline;
    timer_mod(m->rtc_wake_timer, deadline);
}

static void z8_stm32_rtc_reclock(Z8Stm32 *m)
{
    z8_stm32_rtc_alarm_schedule(m);
    if (!z8_stm32_rtc_clocked(m)) {
        timer_del(m->rtc_wake_timer);
    } else if ((m->rtc[Z8_RTC_CR / 4] & 0x400) &&
               !timer_pending(m->rtc_wake_timer)) {
        z8_stm32_rtc_wake_arm(m, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) +
                  z8_stm32_rtc_wake_period(m));
    }
}

static bool z8_stm32_rtc_alarm_match(Z8Stm32 *m, unsigned i,
                                    uint32_t tr, uint32_t dr, unsigned ss)
{
    uint32_t alarm = m->rtc[(0x1c + i * 4) / 4];
    uint32_t sub = m->rtc[(0x44 + i * 4) / 4];
    unsigned compared = (sub >> 24) & 15;
    if (compared ? ((ss ^ sub) & ((1u << compared) - 1)) != 0 :
                   ss != (m->rtc[0x10 / 4] & 32767)) {
        return false;
    }
    if (!(alarm & (1u << 7)) && (alarm & 0x7f) != (tr & 0x7f)) {
        return false;
    }
    if (!(alarm & (1u << 15)) && (alarm & 0x7f00) != (tr & 0x7f00)) {
        return false;
    }
    if (!(alarm & (1u << 23))) {
        unsigned hour = z8_unbcd((alarm >> 16) & 0x3f);
        if (m->rtc[Z8_RTC_CR / 4] & (1u << 6)) {
            hour = hour % 12 + ((alarm & (1u << 22)) ? 12 : 0);
        }
        if (hour != z8_unbcd((tr >> 16) & 0x3f)) {
            return false;
        }
    }
    if (!(alarm & (1u << 31))) {
        unsigned day = alarm & (1u << 30) ? (dr >> 13) & 7 : dr & 0x3f;
        unsigned want = (alarm >> 24) & ((alarm & (1u << 30)) ? 7 : 0x3f);
        if (want != day) {
            return false;
        }
    }
    return true;
}

static void z8_stm32_rtc_alarm_tick(void *opaque)
{
    Z8Stm32 *m = opaque;
    uint32_t tr, dr;
    if (!z8_stm32_rtc_clocked(m)) {
        return;
    }
    z8_stm32_rtc_from_s(z8_stm32_rtc_now_s(m), &tr, &dr);
    unsigned ss = z8_stm32_rtc_ss(m);
    for (unsigned i = 0; i < 2; i++) {
        if ((m->rtc[Z8_RTC_CR / 4] & (0x100u << i)) &&
            z8_stm32_rtc_alarm_match(m, i, tr, dr, ss)) {
            m->rtc[Z8_RTC_ISR / 4] |= 0x100u << i;
            m->rtc_alarm_events[i]++;
        }
    }
    z8_stm32_rtc_irq(m);
    z8_stm32_rtc_alarm_schedule(m);
}

static void z8_stm32_rtc_wake_tick(void *opaque)
{
    Z8Stm32 *m = opaque;
    if (!z8_stm32_rtc_clocked(m) || !(m->rtc[Z8_RTC_CR / 4] & 0x400)) {
        return;
    }
    int64_t period = z8_stm32_rtc_wake_period(m);
    int64_t deadline = m->rtc_wake_deadline;
    int64_t now = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    uint64_t count = 1 + MAX(0, now - deadline) / period;
    m->rtc_wake_events += count;
    m->rtc[Z8_RTC_ISR / 4] |= 0x400;
    z8_stm32_rtc_irq(m);
    z8_stm32_rtc_wake_arm(m, deadline + count * period);
}

static bool z8_stm32_rtc_valid(hwaddr off)
{
    return off <= 0x48 || (off >= 0x50 && off <= 0x9c);
}

static uint64_t z8_stm32_rtc_read(void *opaque, hwaddr off, unsigned size)
{
    Z8Stm32 *m = opaque;
    uint32_t isr, tr, dr;

    if (size != 4 || !z8_stm32_rtc_valid(off) || (off & 3)) {
        z8_stm32_stop("RTC", Z8_STM32_RTC_BASE + off, size, false, 0);
        return 0;
    }
    switch (off) {
    case Z8_RTC_TR:
    case Z8_RTC_DR:
        if (m->rtc[Z8_RTC_ISR / 4] & (1u << 7)) {      /* INIT: as written */
            return m->rtc[off / 4];
        }
        z8_stm32_rtc_from_s(z8_stm32_rtc_now_s(m), &tr, &dr);
        return off == Z8_RTC_TR ? tr : dr;
    case Z8_RTC_ISR:
        isr = m->rtc[off / 4] & 0x0003ff80;     /* INIT and the event flags */
        if (isr & (1u << 7)) {
            isr |= 1u << 6;                     /* INITF */
        }
        isr |= 1u << 5;                         /* RSF */
        if (m->rtc[Z8_RTC_DR / 4] >> 16) {
            isr |= 1u << 4;                     /* INITS: year set */
        }
        if (!(m->rtc[Z8_RTC_CR / 4] & (1u << 10))) {
            isr |= 1u << 2;                     /* WUTWF: WUTE off */
        }
        if (!(m->rtc[Z8_RTC_CR / 4] & (1u << 9))) {
            isr |= 1u << 1;                     /* ALRBWF */
        }
        if (!(m->rtc[Z8_RTC_CR / 4] & (1u << 8))) {
            isr |= 1u << 0;                     /* ALRAWF */
        }
        return isr;
    case Z8_RTC_WPR:
        return 0;
    case Z8_RTC_SSR:
        return z8_stm32_rtc_ss(m);
    }
    return m->rtc[off / 4];
}

static void z8_stm32_rtc_write(void *opaque, hwaddr off, uint64_t value,
                                unsigned size)
{
    Z8Stm32 *m = opaque;
    bool locked = m->rtc_wpr != 2;

    if (size != 4 || !z8_stm32_rtc_valid(off) || (off & 3)) {
        z8_stm32_stop("RTC", Z8_STM32_RTC_BASE + off, size, true, value);
        return;
    }
    if (off == Z8_RTC_WPR) {           /* 0xca then 0x53 unlocks */
        m->rtc_wpr = value == 0xca ? 1 : (value == 0x53 && m->rtc_wpr == 1)
                     ? 2 : 0;
        return;
    }
    if (off >= 0x50) {                  /* backup registers: no lock */
        m->rtc[off / 4] = value;
        return;
    }
    if (locked && off != Z8_RTC_ISR) {
        return;                         /* protected configuration */
    }
    switch (off) {
    case Z8_RTC_ISR: {
        uint32_t old = m->rtc[off / 4];
        uint32_t keep = (old & ~0x3ff00u) | (value & 0x3ff00u & old);

        /* Event flags clear even with WPR locked; INIT remains protected. */
        if (locked) {
            value = (value & ~(1u << 7)) | (old & (1u << 7));
        }
        m->rtc[off / 4] = (keep & ~(1u << 7)) | (value & (1u << 7));
        if ((old & (1u << 7)) && !(value & (1u << 7))) {
            m->rtc_base_s = z8_stm32_rtc_to_s(m->rtc[Z8_RTC_TR / 4],
                                               m->rtc[Z8_RTC_DR / 4]);
            m->rtc_epoch_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
        }
        z8_stm32_rtc_irq(m);
        z8_stm32_rtc_reclock(m);
        return;
    }
    case Z8_RTC_TR:
    case Z8_RTC_DR:
    case 0x10:                          /* PRER */
        if (!(m->rtc[Z8_RTC_ISR / 4] & (1u << 7))) {
            return;                     /* only in initialisation mode */
        }
        break;
    case Z8_RTC_CR:
        if (m->rtc[off / 4] & 0x400) {
            value = (value & ~7u) | (m->rtc[off / 4] & 7);
        }
        if (!(value & 0x400)) {
            timer_del(m->rtc_wake_timer);
        } else if (!(m->rtc[off / 4] & 0x400) && z8_stm32_rtc_clocked(m)) {
            m->rtc[off / 4] = value;
            z8_stm32_rtc_wake_arm(m, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) +
                      z8_stm32_rtc_wake_period(m));
        }
        break;
    case 0x14:                          /* WUTR: writable only when disabled */
        if (m->rtc[Z8_RTC_CR / 4] & 0x400) {
            return;
        }
        value &= 0xffff;
        break;
    case 0x1c:
    case 0x20:
    case 0x44:
    case 0x48: {
        unsigned i = off == 0x20 || off == 0x48;
        if (m->rtc[Z8_RTC_CR / 4] & (0x100u << i)) {
            return;
        }
        break;
    }
    }
    m->rtc[off / 4] = value;
    z8_stm32_rtc_irq(m);
    z8_stm32_rtc_reclock(m);
}

static const MemoryRegionOps z8_stm32_rtc_ops = {
    .read = z8_stm32_rtc_read,
    .write = z8_stm32_rtc_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4 },
};

/* mcu-rtc=: "host" -- QEMU's RTC time at machine start (the host's clock,
 * or -rtc base=), "unset", or YYYY-MM-DDTHH:MM:SS, 2000..2099. The
 * calendar is taken as UTC, as the RTOS's own reports print it. */
static bool z8_stm32_rtc_option(Z8Stm32 *m, const char *value,
                                 Error **errp)
{
    struct tm t = { 0 };

    if (!value || !strcmp(value, "host")) {
        qemu_get_timedate(&t, 0);
    } else if (!strcmp(value, "unset")) {
        m->rtc_running = false;     /* and the clock chip reads zeros */
        return true;
    } else if (sscanf(value, "%d-%d-%dT%d:%d:%d", &t.tm_year, &t.tm_mon,
                      &t.tm_mday, &t.tm_hour, &t.tm_min, &t.tm_sec) != 6 ||
               t.tm_year < 2000 || t.tm_year > 2099 || t.tm_mon < 1 ||
               t.tm_mon > 12 || t.tm_mday < 1 || t.tm_mday > 31 ||
               t.tm_hour > 23 || t.tm_min > 59 || t.tm_sec > 59) {
        error_setg(errp, "mcu-rtc: want host, unset or "
                   "YYYY-MM-DDTHH:MM:SS (2000..2099), not '%s'", value);
        return false;
    } else {
        t.tm_year -= 1900;
        t.tm_mon -= 1;
    }
    if (t.tm_year < 100 || t.tm_year > 199) {
        error_setg(errp, "mcu-rtc: the MCU's calendar holds 2000..2099");
        return false;
    }
    m->rtc_running = true;
    m->rtc_start_s = mktimegm(&t) - 946684800;
    /* The clock chip on I2C1 kept the same time (z8_stm32_clock_regs). */
    for (unsigned i = 0; i < ARRAY_SIZE(m->i2c_dev); i++) {
        if (m->i2c_dev[i].bus == 0 && m->i2c_dev[i].addr == 0x32) {
            m->i2c_dev[i].clock = true;
            m->i2c_dev[i].clock_base_s = m->rtc_start_s;
            m->i2c_dev[i].clock_epoch_ns =
                qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
        }
    }
    return true;
}

static void z8_stm32_rtc_reset(Z8Stm32 *m)
{
    if (m->rtc_alarm_timer) {
        timer_del(m->rtc_alarm_timer);
        timer_del(m->rtc_wake_timer);
    }
    if (m->rtc_alarm_level) {
        qemu_set_irq(qdev_get_gpio_in(DEVICE(&m->exti), 17), 0);
    }
    if (m->rtc_wake_level) {
        qemu_set_irq(qdev_get_gpio_in(DEVICE(&m->exti), 22), 0);
    }
    m->rtc_alarm_level = m->rtc_wake_level = false;
    m->rtc_alarm_events[0] = m->rtc_alarm_events[1] = m->rtc_wake_events = 0;
    /* The backup domain survives a system reset on the part; here a cold
     * start is all there is. Without mcu-rtc the calendar starts at
     * 2000-01-01 00:00 and INITS stays clear until the firmware sets a date
     * -- a body whose clock battery has run down. With it (the board's
     * default, "host"), the calendar has kept time and reads mcu-rtc's
     * moment at power-on, INITS set: a body whose clock was set before it
     * was switched off. DECLARED: which, and when. */
    memset(m->rtc, 0, sizeof(m->rtc));
    m->rtc[Z8_RTC_DR / 4] = 0x00002101;        /* reset value: Mon 01-01 */
    m->rtc[0x10 / 4] = 0x007f00ff;              /* PRER */
    m->rtc_base_s = 0;
    if (m->rtc_running) {
        /* What a kept backup domain looks like to this image's check,
         * sub_803E8B8 -- the clock counts as lost unless RCC_BDCR has
         * LSEON (bit 0) and RTCEN (bit 15), RTC_CR has its BKP bit (18)
         * and backup register 19 has bits 8..15 non-zero. That byte is the
         * EXPEED's: sub_803EC00 stores it on event 0x40 and hands it back
         * at start-up on event 0x20 (message 0x42030004). Observed: the
         * EXPEED stores 1 when it has put its own default date in the
         * clock (2024-01-01, family 7 kind 5) and 2 once a date has been
         * set in SETUP > Time zone and date (family 7 kind 3) -- and with
         * 1 it puts its default in again at the next start. 2 here, a
         * clock that was set. The RTC clocked from the LSE (RTCSEL 01) is
         * DECLARED with it. */
        m->rcc[Z8_RCC_BDCR / 4] = 0x00008101;
        m->rtc[Z8_RTC_CR / 4] = 1u << 18;
        m->rtc[(0x50 + 4 * 19) / 4] = 0x00000200;
        m->rtc_base_s = m->rtc_start_s;
        z8_stm32_rtc_from_s(m->rtc_start_s, &m->rtc[Z8_RTC_TR / 4],
                             &m->rtc[Z8_RTC_DR / 4]);
    }
    m->rtc_epoch_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    m->rtc_wpr = 0;
}

/* ------------------------------------------------------------------ */
/* I2C1..3 (RM0386 section 27): the v1 master, polled or interrupt.    */
/* ------------------------------------------------------------------ */
/*
 * Master mode only, which is all the image was seen to use. The bus has
 * no devices yet: every address NACKs (SR1.AF), and each is named once,
 * which is how the parts the MCU talks to are found. Clock stretching,
 * arbitration, 10-bit addressing, PEC, SMBus and DMA are not modelled.
 */
typedef struct Z8Stm32I2c Z8Stm32I2c;

static const hwaddr z8_stm32_i2c_base[3] = {
    0x40005400, 0x40005800, 0x40005c00,
};
static const int z8_stm32_i2c_irqn[3][2] = { { 31, 32 }, { 33, 34 }, { 72, 73 } };

#define Z8_I2C_SR1_SB    (1u << 0)
#define Z8_I2C_SR1_ADDR  (1u << 1)
#define Z8_I2C_SR1_BTF   (1u << 2)
#define Z8_I2C_SR1_RXNE  (1u << 6)
#define Z8_I2C_SR1_TXE   (1u << 7)
#define Z8_I2C_SR1_AF    (1u << 10)
#define Z8_I2C_SR1_ERR   0xdf00u       /* BERR ARLO AF OVR PECERR TIMEOUT SMBALERT */

static void z8_stm32_i2c_irq(Z8Stm32I2c *c)
{
    bool ev = (c->cr2 & (1u << 9)) &&
              ((c->sr1 & 0x1f) ||
               ((c->cr2 & (1u << 10)) &&
                (c->sr1 & (Z8_I2C_SR1_RXNE | Z8_I2C_SR1_TXE))));
    bool er = (c->cr2 & (1u << 8)) && (c->sr1 & Z8_I2C_SR1_ERR);

    qemu_set_irq(c->ev_irq, ev);
    qemu_set_irq(c->er_irq, er);
}

/*
 * The devices on the MCU's buses. Their parts are not identified yet; each
 * is a declared register file, the same choice the main board makes for an
 * unidentified block: 256 byte registers, the first byte written after the
 * address sets the pointer, data auto-increments. What the firmware needs
 * from them at boot is that a write reads back -- sub_803B724 writes the
 * device at 0x61 (registers 2, 5, 8) and checks it three times, and resets
 * the MCU (power state 11, sub_804A6A8) when the check fails. Every other
 * address NACKs and is named once.
 */
typedef struct Z8Stm32I2cDev Z8Stm32I2cDev;

static const struct { uint8_t bus, addr; } z8_stm32_i2c_dev_at[6] = {
    { 0, 0x18 }, { 0, 0x32 }, { 0, 0x61 }, { 0, 0x69 }, /* I2C1 */
    { 3, 0x22 }, { 3, 0x23 },                   /* FMPI2C1 */
};

/*
 * The two FMPI2C1 devices are the body's button expanders. The switch
 * service reads each one's three input ports (sub_80352C4 -> sub_8034800:
 * 8-bit addresses 0x44 and 0x46, register 0, 3 bytes, table 0x80583c8)
 * and takes a button as pressed when its input bit is 0 and it is enabled
 * (sub_803D998 / sub_803DA14: ~input & mask) -- active low. MENU, PLAY,
 * OK, the multi-selector, the sub-selector, DISP, i, DELETE, the zoom
 * buttons, Fn1/Fn2, the movie-record button and more are here (the map is
 * in the donor nikon-z63-mcukeys.h; Z8 mappings are separate). While the camera is on, the expander task
 * ("IoExpCyc", sub_8034D18) reads both every ~12 ms (sub_803505C ->
 * sub_80352C4) and hands the bytes to the key task (sub_80449F4 ->
 * sub_8044960), so no interrupt line is needed for a press to be seen.
 * Which MCU pins the parts' INT outputs reach is not known; asserting one
 * on a guessed pin is worse than none (PC7 is a shutter position sensor,
 * and EXTI7/PG7 reset the MCU), so INT is not modelled.
 *
 * Read as the plain register file above, every input was 0: every one of
 * those buttons held, for ever. So these two answer their input ports
 * (registers 0..2) from pin levels instead -- 1, released, unless the board
 * presses a button (z8_stm32_expander_set). That is the input port of a
 * 24-bit I/O expander of the TCA6424A kind, whose two addresses these
 * are; the part is not identified, and everything else in it is still the
 * register file. DECLARED: released = 1 (the firmware's active-low
 * reading).
 */
static const uint8_t z8_stm32_expander_at[2] = { 0x22, 0x23 };

static Z8Stm32I2cDev *z8_stm32_i2c_find(Z8Stm32 *m, unsigned bus,
                                          uint8_t addr, bool read,
                                          uint8_t *nack_named)
{
    for (unsigned i = 0; i < ARRAY_SIZE(m->i2c_dev); i++) {
        Z8Stm32I2cDev *d = &m->i2c_dev[i];

        if (d->bus == bus && d->addr == addr) {
            if (!read) {
                d->ptr_set = false;
            }
            return d;
        }
    }
    if (!(nack_named[addr / 8] & (1u << (addr % 8)))) {
        nack_named[addr / 8] |= 1u << (addr % 8);
        error_report("Z8_STM32: %s%u address 0x%02x (%s): no device -- NACK "
                     "(pc=0x%08x)", bus == 3 ? "FMPI2C" : "I2C",
                     bus == 3 ? 1 : bus + 1, addr, read ? "read" : "write",
                     z8_stm32_pc());
    }
    return NULL;
}

/*
 * The clock chip. At power-on the MCU's clock task reads the time from
 * I2C1 address 0x32 -- sub_803F714 -> sub_803F3FE -> sub_803EEC4 ->
 * sub_803F090: HAL_I2C_Mem_Read of 7 bytes from register 0x10, BCD, the
 * bytes taken as seconds, minutes, hours, (one skipped), day, month, year
 * -- and hands it on as message 0x42040001 (sub_803FF9C), which sets the
 * MCU's own RTC from it (sub_803FA7C, event 0x8000000 -> sub_803EE1C)
 * and so becomes the time the MCU reports to the EXPEED (family 7 kind
 * 1). That register map, at that address, is a battery-backed real-time
 * clock of the Epson RX-8010SJ kind (0x10 SEC .. 0x16 YEAR, 0x13 a
 * one-hot weekday). As a plain register file it read all zeros, so every
 * start set the MCU to 2000-00-00, the EXPEED replaced that with its
 * default (2024-01-01, family 7 kind 5) and showed the clock as not set.
 * Here registers 0x10..0x16 count from mcu-rtc's moment (nikon-z8.c) on
 * QEMU's virtual clock, and a write to them sets the count; the rest of
 * the chip (alarm, timer, flags, control) is still the register file.
 * DECLARED: the part, and that its clock ran while the camera was off.
 */
#define Z8_CLOCK_SEC   0x10
#define Z8_CLOCK_YEAR  0x16

static void z8_stm32_clock_regs(Z8Stm32I2cDev *d)
{
    int64_t s = d->clock_base_s + (qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) -
                                   d->clock_epoch_ns) / NANOSECONDS_PER_SECOND;
    time_t tt = s + 946684800;
    struct tm t;

    gmtime_r(&tt, &t);
    d->regs[0x10] = z8_bcd(t.tm_sec);
    d->regs[0x11] = z8_bcd(t.tm_min);
    d->regs[0x12] = z8_bcd(t.tm_hour);
    d->regs[0x13] = 1u << t.tm_wday;
    d->regs[0x14] = z8_bcd(t.tm_mday);
    d->regs[0x15] = z8_bcd(t.tm_mon + 1);
    d->regs[0x16] = z8_bcd(t.tm_year - 100);
}

static void z8_stm32_clock_set(Z8Stm32I2cDev *d)
{
    struct tm t = {
        .tm_sec = z8_unbcd(d->regs[0x10] & 0x7f),
        .tm_min = z8_unbcd(d->regs[0x11] & 0x7f),
        .tm_hour = z8_unbcd(d->regs[0x12] & 0x3f),
        .tm_mday = MAX(z8_unbcd(d->regs[0x14] & 0x3f), 1),
        .tm_mon = MAX(z8_unbcd(d->regs[0x15] & 0x1f), 1) - 1,
        .tm_year = 100 + z8_unbcd(d->regs[0x16]),
    };

    d->clock_base_s = mktimegm(&t) - 946684800;
    d->clock_epoch_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
}

static void z8_stm32_i2c_dev_write(Z8Stm32I2cDev *d, uint8_t b)
{
    if (!d->ptr_set) {
        d->ptr = b;
        d->ptr_set = true;
        if (d->clock) {
            z8_stm32_clock_regs(d);    /* one reading per transaction */
        }
        return;
    }
    if (d->clock && d->ptr >= Z8_CLOCK_SEC && d->ptr <= Z8_CLOCK_YEAR) {
        d->regs[d->ptr++] = b;
        z8_stm32_clock_set(d);
        d->writes++;
        return;
    }
    d->regs[d->ptr++] = b;
    if (d->bus == 0 && d->addr == 0x18 && d->ptr == 0x32) {
        /* C2.01's 0x210 query reads status at 0x10 through the MCU.
         * After writing control 0x0404 it polls bit 7 (403230f8), then
         * after each 0x0808 commit it polls bit 3 (40322ffc).
         * Complete these virtual-device commands synchronously. The
         * physical part and timing are unknown; no calibration or sample
         * data is synthesized. Other register writes keep normal storage. */
        uint16_t control = d->regs[0x30] | (d->regs[0x31] << 8);

        if (control == 0x0404) {
            d->regs[0x10] = (d->regs[0x10] & ~0x08) | 0x80;
        } else if (control == 0x0808) {
            d->regs[0x10] |= 0x08;
        }
    }
    d->writes++;
}

static uint8_t z8_stm32_i2c_dev_read(Z8Stm32I2cDev *d)
{
    d->reads++;
    if (d->expander && d->ptr < 3) {
        uint8_t v = d->inputs >> (8 * d->ptr);

        /* The first reads, and then every read that sees a change. */
        if (d->ptr == 0 && (d->reads <= 4 || d->inputs != d->logged)) {
            error_report("Z8_STM32: button expander 0x%02x inputs read: "
                         "0x%06x (pc=0x%08x, read %" PRIu64 ")", d->addr,
                         d->inputs, z8_stm32_pc(), d->reads);
            d->logged = d->inputs;
        }
        d->ptr++;
        return v;
    }
    return d->regs[d->ptr++];
}

/*
 * I2C v1 receive: DR and, behind it, the shift register (RM0402 24.3.3).
 * The peripheral receives while there is room -- into DR, then into the
 * shift register, where it stalls with BTF set -- and a byte received
 * while ACK is clear (with POS, the byte after the first) is NACKed and is
 * the last. Reading DR moves the shift register's byte up and lets the
 * next one in. HAL's endings depend on that pipeline: for the last three
 * bytes it waits for BTF, clears ACK, reads N-2 (byte N then arrives
 * NACKed), sets STOP and reads N-1 and N -- with one stage the model
 * NACKed N-1 and handed it out twice (a 7-byte read of the clock chip at
 * I2C1 0x32 returned its month register in place of its year).
 */
static void z8_stm32_i2c_rx(Z8Stm32I2c *c, bool first)
{
    bool ack = c->cr1 & (1u << 10), pos = c->cr1 & (1u << 11);

    while (c->dev && !c->last_sent &&
           (!(c->sr1 & Z8_I2C_SR1_RXNE) || !c->sh_full)) {
        uint8_t b = z8_stm32_i2c_dev_read(c->dev);

        if (!(c->sr1 & Z8_I2C_SR1_RXNE)) {
            c->dr = b;
            c->sr1 |= Z8_I2C_SR1_RXNE;
        } else {
            c->sh = b;
            c->sh_full = true;
        }
        if (!ack && !(first && pos) && !(c->cr2 & (1u << 11))) {
            c->last_sent = true;
        }
        first = false;
    }
    if (c->sh_full) {
        c->sr1 |= Z8_I2C_SR1_BTF;
    }
}

/* The ARM side took DR: the shift register's byte moves up. */
static void z8_stm32_i2c_pop(Z8Stm32I2c *c)
{
    c->sr1 &= ~(Z8_I2C_SR1_RXNE | Z8_I2C_SR1_BTF);
    if (c->sh_full) {
        c->dr = c->sh;
        c->sh_full = false;
        c->sr1 |= Z8_I2C_SR1_RXNE;
    }
}

/* I2C v1 with CR2.DMAEN: TXE and RXNE are DMA requests (RM0402 24.3.7).
 * The bytes move at once; with LAST the final received byte is NACKed. */
static void z8_stm32_i2c_pump(Z8Stm32I2c *c)
{
    uint32_t par = z8_stm32_i2c_base[c->bus] + 0x10, v;

    if (!(c->cr2 & (1u << 11)) || !c->selected || !c->dev ||
        (c->sr1 & Z8_I2C_SR1_ADDR)) {
        return;
    }
    if (!c->reading) {
        while ((c->sr1 & Z8_I2C_SR1_TXE) && z8_stm32_dma_tx(c->mcu, par, &v)) {
            z8_stm32_i2c_dev_write(c->dev, v);
            c->sr1 |= Z8_I2C_SR1_TXE | Z8_I2C_SR1_BTF;
        }
    } else {
        while ((c->sr1 & Z8_I2C_SR1_RXNE) &&
               z8_stm32_dma_rx(c->mcu, par, c->dr)) {
            z8_stm32_i2c_pop(c);
            z8_stm32_i2c_rx(c, false);
        }
    }
    z8_stm32_i2c_irq(c);
}

static uint64_t z8_stm32_i2c_read(void *opaque, hwaddr off, unsigned size)
{
    Z8Stm32I2c *c = opaque;
    uint32_t v = 0;

    if (size != 4 && size != 2) {
        goto bad;
    }
    switch (off) {
    case 0x00: return c->cr1;
    case 0x04: return c->cr2;
    case 0x08: return c->oar1;
    case 0x0c: return c->oar2;
    case 0x10:
        v = c->dr;
        z8_stm32_i2c_pop(c);
        if (c->reading && c->dev) {
            z8_stm32_i2c_rx(c, false);
        }
        z8_stm32_i2c_irq(c);
        return v;
    case 0x14:
        c->sb_seen = c->sr1 & Z8_I2C_SR1_SB;
        c->addr_seen = c->sr1 & Z8_I2C_SR1_ADDR;
        return c->sr1;
    case 0x18:
        v = c->sr2;
        if (c->addr_seen) {             /* SR1 then SR2 clears ADDR */
            c->addr_seen = false;
            c->sr1 &= ~Z8_I2C_SR1_ADDR;
            if (!c->reading) {
                c->sr1 |= Z8_I2C_SR1_TXE;
            } else {
                c->last_sent = false;
                c->sh_full = false;
                z8_stm32_i2c_rx(c, true);
            }
            z8_stm32_i2c_pump(c);
            z8_stm32_i2c_irq(c);
        }
        return v;
    case 0x1c: return c->ccr;
    case 0x20: return c->trise;
    case 0x24: return c->fltr;
    }
bad:
    z8_stm32_stop("I2C", z8_stm32_i2c_base[c->bus] + off, size, false, 0);
    return 0;
}

static void z8_stm32_i2c_write(void *opaque, hwaddr off, uint64_t value,
                                unsigned size)
{
    Z8Stm32I2c *c = opaque;

    if (size != 4 && size != 2) {
        goto bad;
    }
    switch (off) {
    case 0x00:
        if (value & (1u << 15)) {       /* SWRST */
            c->cr1 = value & (1u << 15);
            c->sr1 = c->sr2 = 0;
            c->selected = false;
            c->dev = NULL;
            c->sh_full = false;
            break;
        }
        c->cr1 = value & ~((1u << 8) | (1u << 9));
        if ((value & 1) && (value & (1u << 8))) {      /* START */
            c->sr1 = (c->sr1 & Z8_I2C_SR1_ERR) | Z8_I2C_SR1_SB;
            c->sr2 |= 3;                                /* MSL BUSY */
        }
        if (value & (1u << 9)) {                        /* STOP */
            /* A byte already received stays in DR until it is read. */
            c->selected = false;
            c->dev = NULL;
            c->sr1 &= Z8_I2C_SR1_ERR | Z8_I2C_SR1_RXNE;
            c->sr2 = 0;
        }
        break;
    case 0x04:
        c->cr2 = value & 0x1f3f;
        z8_stm32_i2c_pump(c);
        break;
    case 0x08: c->oar1 = value; break;
    case 0x0c: c->oar2 = value; break;
    case 0x10:
        c->dr = value;
        if (c->sb_seen && (c->sr1 & Z8_I2C_SR1_SB)) { /* the address byte */
            c->sb_seen = false;
            c->sr1 &= ~Z8_I2C_SR1_SB;
            c->addr = value >> 1;
            c->reading = value & 1;
            c->dev = z8_stm32_i2c_find(c->mcu, c->bus, c->addr, c->reading,
                                        c->nack_named);
            c->selected = c->dev != NULL;
            if (c->selected) {
                c->sr1 |= Z8_I2C_SR1_ADDR;
                c->sr2 = (c->sr2 & ~4u) | (c->reading ? 0 : 4);
            } else {
                c->sr1 |= Z8_I2C_SR1_AF;
            }
        } else if (c->selected && !c->reading) {
            z8_stm32_i2c_dev_write(c->dev, value);
            c->sr1 |= Z8_I2C_SR1_TXE | Z8_I2C_SR1_BTF;
        }
        break;
    case 0x14:                          /* the error flags are rc_w0 */
        c->sr1 &= ~(Z8_I2C_SR1_ERR & ~value);
        break;
    case 0x1c: c->ccr = value; break;
    case 0x20: c->trise = value; break;
    case 0x24: c->fltr = value; break;
    default:
        goto bad;
    }
    z8_stm32_i2c_irq(c);
    return;
bad:
    z8_stm32_stop("I2C", z8_stm32_i2c_base[c->bus] + off, size, true, value);
}

static const MemoryRegionOps z8_stm32_i2c_ops = {
    .read = z8_stm32_i2c_read,
    .write = z8_stm32_i2c_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4 },
};

static void z8_stm32_i2c_reset(Z8Stm32I2c *c)
{
    c->cr1 = c->cr2 = c->oar1 = c->oar2 = c->ccr = c->fltr = 0;
    c->trise = 2;
    c->sr1 = c->sr2 = 0;
    c->selected = c->sb_seen = c->addr_seen = false;
}

/* ------------------------------------------------------------------ */
/* FMPI2C1 at 0x40006000: the v2 (F7/L4-style) I2C, master only.       */
/* ------------------------------------------------------------------ */
/*
 * The block the F410/F412/F413/F446 carry; the image reaches it at
 * pc 0x0804b0f6. As on I2C1..3 no device answers yet: a START sets NACKF
 * and, the master then stopping, STOPF; each address is named once.
 */
#define Z8_STM32_FMPI2C_BASE 0x40006000ULL
#define Z8_FMP_ISR_TXE   (1u << 0)
#define Z8_FMP_ISR_NACKF (1u << 4)
#define Z8_FMP_ISR_STOPF (1u << 5)
#define Z8_FMP_ISR_BUSY  (1u << 15)

/* Event sources (RM0402 FMPI2C_CR1): TXIE/TXIS, RXIE/RXNE, NACKIE/NACKF,
 * STOPIE/STOPF and TCIE with TC or TCR. Polled and DMA transfers never
 * set the first two enables; the button expanders' interrupt-driven reads
 * (nikon-z8-mcukeys.h) wait on RXNE and TC, and without them a read began
 * and never finished. No error source is ever raised here. */
static void z8_stm32_fmpi2c_irq(Z8Stm32 *m)
{
    uint32_t cr1 = m->fmpi2c.cr1, isr = m->fmpi2c.isr;
    bool ev = ((cr1 & (1u << 1)) && (isr & (1u << 1))) ||           /* TXIE */
              ((cr1 & (1u << 2)) && (isr & (1u << 2))) ||           /* RXIE */
              ((cr1 & (1u << 4)) && (isr & Z8_FMP_ISR_NACKF)) ||    /* NACKIE */
              ((cr1 & (1u << 5)) && (isr & Z8_FMP_ISR_STOPF)) ||    /* STOPIE */
              ((cr1 & (1u << 6)) && (isr & ((1u << 6) | (1u << 7)))); /* TCIE */

    qemu_set_irq(m->fmpi2c.ev_irq, ev);
}

/* Advance a v2 transfer: ask for (TXIS) or present (RXNE) the next byte,
 * or end it -- TCR with RELOAD, STOPF with AUTOEND, else TC. */
static void z8_stm32_fmpi2c_step(Z8Stm32 *m)
{
    uint32_t cr2 = m->fmpi2c.cr2;

    if (!m->fmpi2c.dev) {
        return;
    }
    /* TXDMAEN/RXDMAEN (CR1 bits 14/15): the bytes move by DMA at once. */
    while (m->fmpi2c.left) {
        uint32_t par = Z8_STM32_FMPI2C_BASE, v;

        if ((cr2 & (1u << 10)) && (m->fmpi2c.cr1 & (1u << 15)) &&
            !(m->fmpi2c.isr & (1u << 2))) {
            uint8_t b = z8_stm32_i2c_dev_read(m->fmpi2c.dev);

            if (!z8_stm32_dma_rx(m, par + 0x24, b)) {
                m->fmpi2c.rxdr = b;             /* stream not ready: hold it */
                m->fmpi2c.left--;
                m->fmpi2c.isr |= 1u << 2;
                return;
            }
            m->fmpi2c.left--;
        } else if (!(cr2 & (1u << 10)) && (m->fmpi2c.cr1 & (1u << 14)) &&
                   z8_stm32_dma_tx(m, par + 0x28, &v)) {
            z8_stm32_i2c_dev_write(m->fmpi2c.dev, v);
            m->fmpi2c.left--;
        } else {
            break;
        }
    }
    if (m->fmpi2c.left) {
        if (cr2 & (1u << 10)) {
            if (!(m->fmpi2c.isr & (1u << 2))) {
                m->fmpi2c.rxdr = z8_stm32_i2c_dev_read(m->fmpi2c.dev);
                m->fmpi2c.left--;
                m->fmpi2c.isr |= 1u << 2;               /* RXNE */
            }
        } else {
            m->fmpi2c.isr |= (1u << 1) | Z8_FMP_ISR_TXE;   /* TXIS */
        }
        if (m->fmpi2c.left || (cr2 & (1u << 10) ? 0 : 1)) {
            return;
        }
    }
    if (m->fmpi2c.isr & (1u << 2)) {
        return;                                 /* last byte not read yet */
    }
    if (cr2 & (1u << 24)) {
        m->fmpi2c.isr |= 1u << 7;               /* TCR */
    } else if (cr2 & (1u << 25)) {
        m->fmpi2c.dev = NULL;                   /* AUTOEND: STOP */
        m->fmpi2c.isr = (m->fmpi2c.isr & ~Z8_FMP_ISR_BUSY) |
                        Z8_FMP_ISR_STOPF | Z8_FMP_ISR_TXE;
    } else {
        m->fmpi2c.isr |= 1u << 6;               /* TC */
    }
}

static uint64_t z8_stm32_fmpi2c_read(void *opaque, hwaddr off, unsigned size)
{
    Z8Stm32 *m = opaque;

    if (size == 4) {
        switch (off) {
        case 0x00: return m->fmpi2c.cr1;
        case 0x04: return m->fmpi2c.cr2;
        case 0x08: return m->fmpi2c.oar1;
        case 0x0c: return m->fmpi2c.oar2;
        case 0x10: return m->fmpi2c.timingr;
        case 0x14: return m->fmpi2c.timeoutr;
        case 0x18: return m->fmpi2c.isr;
        case 0x24: {                            /* RXDR */
            uint8_t v = m->fmpi2c.rxdr;

            m->fmpi2c.isr &= ~(1u << 2);
            z8_stm32_fmpi2c_step(m);
            z8_stm32_fmpi2c_irq(m);
            return v;
        }
        }
    }
    z8_stm32_stop("FMPI2C", Z8_STM32_FMPI2C_BASE + off, size, false, 0);
    return 0;
}

static void z8_stm32_fmpi2c_write(void *opaque, hwaddr off, uint64_t value,
                                   unsigned size)
{
    Z8Stm32 *m = opaque;

    if (size == 4) {
        switch (off) {
        case 0x00:
            m->fmpi2c.cr1 = value;
            if (!(value & 1)) {                 /* PE off: software reset */
                m->fmpi2c.isr = Z8_FMP_ISR_TXE;
            }
            z8_stm32_fmpi2c_irq(m);
            return;
        case 0x04: {
            unsigned addr = (value >> 1) & 0x7f;
            bool read = value & (1u << 10);

            m->fmpi2c.cr2 = value & ~((1u << 13) | (1u << 14));
            if (value & (1u << 13)) {           /* START (or repeated) */
                m->fmpi2c.dev = z8_stm32_i2c_find(m, 3, addr, read,
                                                   m->fmpi2c.nack_named);
                m->fmpi2c.isr &= ~((1u << 6) | (1u << 7));      /* TC TCR */
                if (!m->fmpi2c.dev) {
                    m->fmpi2c.isr |= Z8_FMP_ISR_NACKF | Z8_FMP_ISR_STOPF;
                } else {
                    m->fmpi2c.isr |= Z8_FMP_ISR_BUSY;
                    m->fmpi2c.left = (value >> 16) & 0xff;
                    z8_stm32_fmpi2c_step(m);
                }
            } else if ((m->fmpi2c.isr & (1u << 7)) && m->fmpi2c.dev) {
                m->fmpi2c.isr &= ~(1u << 7);    /* TCR: reload NBYTES */
                m->fmpi2c.left = (value >> 16) & 0xff;
                z8_stm32_fmpi2c_step(m);
            }
            if (value & (1u << 14)) {           /* STOP */
                m->fmpi2c.dev = NULL;
                m->fmpi2c.isr = (m->fmpi2c.isr & ~(Z8_FMP_ISR_BUSY | 0xc6)) |
                                Z8_FMP_ISR_STOPF | Z8_FMP_ISR_TXE;
            }
            z8_stm32_fmpi2c_irq(m);
            return;
        }
        case 0x08: m->fmpi2c.oar1 = value; return;
        case 0x0c: m->fmpi2c.oar2 = value; return;
        case 0x10: m->fmpi2c.timingr = value; return;
        case 0x14: m->fmpi2c.timeoutr = value; return;
        case 0x1c:                              /* ICR */
            m->fmpi2c.isr &= ~(value & 0x3f38);
            z8_stm32_fmpi2c_irq(m);
            return;
        case 0x28:                              /* TXDR */
            if (m->fmpi2c.dev && m->fmpi2c.left) {
                z8_stm32_i2c_dev_write(m->fmpi2c.dev, value);
                m->fmpi2c.left--;
                m->fmpi2c.isr &= ~(1u << 1);
                z8_stm32_fmpi2c_step(m);
            }
            z8_stm32_fmpi2c_irq(m);
            return;
        }
    }
    z8_stm32_stop("FMPI2C", Z8_STM32_FMPI2C_BASE + off, size, true, value);
}

static const MemoryRegionOps z8_stm32_fmpi2c_ops = {
    .read = z8_stm32_fmpi2c_read,
    .write = z8_stm32_fmpi2c_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4 },
};

/* ------------------------------------------------------------------ */
/* SYSCFG (RM0402 section 7): memory remap, EXTI line routing.         */
/* ------------------------------------------------------------------ */
/*
 * Own model: QEMU's stm32f4xx-syscfg routes only port A correctly (its
 * set_irq indexes EXTICR and its outputs with port*16+pin unreduced).
 * EXTICR1-4 select, per EXTI line n, which port's pin n drives it;
 * z8_stm32_gpio_drive() consults them. +0x24 is read-modify-written by
 * the image (bit 0, pc 0x0804b002) and has no meaning in the manuals at
 * hand (F412 CFGR is +0x2c); storage, like CMPCR.
 */
#define Z8_STM32_SYSCFG_BASE 0x40013800ULL

static uint64_t z8_stm32_syscfg_read(void *opaque, hwaddr off, unsigned size)
{
    Z8Stm32 *m = opaque;

    if (size != 4 || off >= sizeof(m->syscfg) || off == 0x18 ||
        off == 0x1c) {
        z8_stm32_stop("SYSCFG", Z8_STM32_SYSCFG_BASE + off, size, false, 0);
        return 0;
    }
    if (off == 0x20) {
        return m->syscfg[off / 4] | ((m->syscfg[off / 4] & 1) << 8); /* READY */
    }
    return m->syscfg[off / 4];
}

static void z8_stm32_syscfg_write(void *opaque, hwaddr off, uint64_t value,
                                   unsigned size)
{
    Z8Stm32 *m = opaque;

    if (size != 4 || off >= sizeof(m->syscfg) || off == 0x18 ||
        off == 0x1c) {
        z8_stm32_stop("SYSCFG", Z8_STM32_SYSCFG_BASE + off, size, true,
                       value);
        return;
    }
    m->syscfg[off / 4] = value;
}

static const MemoryRegionOps z8_stm32_syscfg_ops = {
    .read = z8_stm32_syscfg_read,
    .write = z8_stm32_syscfg_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4 },
};

/* ------------------------------------------------------------------ */
/* SPI1 at 0x40013000                                                  */
/* ------------------------------------------------------------------ */
/*
 * The first peripheral the image reaches past the timer work: pc
 * 0x0804d122 loads the register at offset 0, clears bit 6 and stores it
 * back. On SPI that is CR1.SPE (enable), and the surrounding code is
 * HAL_SPI's deinit shape (handle->State at +0x51, Instance at +0). The
 * alternative reading -- that 0x40013000 is only an anchor for SYSCFG at
 * +0x808 -- is wrong at this site: the offset here is 0. (Both exist:
 * 0x0804b8de does use [r1, #0x808] for SYSCFG_EXTICR1, from the same
 * pool constant. The two need not share an author's intent.)
 *
 * REGISTER FILE PLUS, not behaviour: SR reports TXE|RXNE so the driver's
 * polls succeed and the transfer path is reached. What a transfer
 * actually does is the link question, and it is not answered here -- see
 * the note at the bottom of this block. Every offset touched is named
 * once, with its accessor, because which offsets the image uses is the
 * evidence that identifies the device.
 */
/* The SPI family (RM0386 28.5): SPI1 at 0x40013000, SPI2 0x40003800,
 * SPI3 0x40003c00, SPI4 0x40013400, SPI5 0x40015000, SPI6 0x40015400.
 *
 * This is the link. The first peripheral the image reaches past the timer
 * work is SPI1: pc 0x0804d122 loads offset 0, clears bit 6 and stores it
 * back -- CR1.SPE, the enable -- and the surrounding code is HAL_SPI's
 * deinit shape (handle->State at +0x51, Instance at +0). Then the running
 * module at 0x0803922x, the one §9b could not get to run, touches CR2,
 * DR and SR in that order: a transfer. An MCU that is the SPI master is
 * also exactly what the other side describes -- "the MCU, not the EXPEED,
 * supplies the clock". (0x40013000 also appears as an anchor for SYSCFG
 * at [base + 0x808]; 0x0804b8de does use that form. Both readings are
 * real, at different sites.)
 *
 * REGISTER FILE PLUS, not behaviour. SR reports TXE|RXNE so the driver's
 * polls succeed and its transfer loop is reached; a word written to DR is
 * held, and a DR read hands back whatever was last put there (0 until
 * something does). What a transfer *means* -- which words go to which
 * SIO instance on the EXPEED, and what the EXPEED sends back -- is the
 * wiring step, and is deliberately not invented here. Every register the
 * image touches is named once, with its accessor, because which registers
 * it uses is the evidence that identifies the device.
 */
static const hwaddr z8_stm32_spi_base[Z8_STM32_SPI_N] = {
    0x40013000,     /* SPI1 */
    0x40003800,     /* SPI2 */
    0x40003c00,     /* SPI3 */
    0x40013400,     /* SPI4 */
    0x40015000,     /* SPI5 */
    0x40015400,     /* SPI6 */
};
static const int z8_stm32_spi_irq[Z8_STM32_SPI_N] = {
    35, 36, 51, 84, 85, 86,
};

#define Z8_SPI_CR1     0x00
#define Z8_SPI_CR2     0x04
#define Z8_SPI_SR      0x08
#define Z8_SPI_DR      0x0c

/* SR bits the driver tests (RM0386 28.5.5). */
#define Z8_SPI_SR_RXNE (1 << 0)
#define Z8_SPI_SR_TXE  (1 << 1)
#define Z8_SPI_SR_BSY  (1 << 7)

static void z8_stm32_spi_note(Z8Stm32Spi *sp, hwaddr off, bool write)
{
    /* Registers are four bytes apart, so one bit per register fits. */
    static const char *const names[] = {
        [0x00] = "CR1", [0x04] = "CR2", [0x08] = "SR", [0x0c] = "DR",
        [0x10] = "CRCPR", [0x14] = "RXCRCR", [0x18] = "TXCRCR",
        [0x1c] = "I2SCFGR", [0x20] = "I2SPR",
    };
    unsigned bit = off / 4;
    const char *name = off < ARRAY_SIZE(names) && names[off] ? names[off] : "?";

    if (bit >= 32 || (sp->seen & (1u << bit))) {
        return;
    }
    sp->seen |= 1u << bit;
    error_report("Z8_STM32: SPI%u first %s of %s (off 0x%02x) pc=0x%08x",
                 sp->inst + 1, write ? "write" : "read", name,
                 (unsigned)off, z8_stm32_pc());
}

/* The SPI's interrupt (RM0386 26.3.11), level-sensitive as on the part:
 * TXE with CR2.TXEIE or RXNE with CR2.RXNEIE, while CR1.SPE is set. Both
 * flags always read set here (see the SR read below), so enabling either
 * interrupt enters the handler at once and a HAL interrupt-driven transfer
 * moves one word per entry until it disables the interrupt again. That is
 * how the SbCtl task's transfers on SPI3 finish; without the line its HAL
 * send waited for a TXE interrupt that never came. No error is ever
 * raised, so ERRIE alone asserts nothing -- which matters for SPI1/2/4,
 * whose CR2 holds ERRIE beside their DMA enables. */
static void z8_stm32_spi_irq_update(Z8Stm32Spi *sp)
{
    qemu_set_irq(sp->irq, (sp->r[Z8_SPI_CR1 / 4] & 0x40) &&
                          (sp->r[Z8_SPI_CR2 / 4] & 0xc0));
}

static uint64_t z8_stm32_spi_read(void *opaque, hwaddr off, unsigned size)
{
    Z8Stm32Spi *sp = opaque;

    z8_stm32_spi_note(sp, off, false);

    switch (off) {
    case Z8_SPI_SR:
        /* Not busy, and both directions always ready: there is no peer on
         * the other end of this bus yet, so a driver that waits on a flag
         * would wait for ever. Saying "ready" lets it reach its transfer
         * and is the honest answer for a bus nobody is clocking. */
        return Z8_SPI_SR_TXE | Z8_SPI_SR_RXNE;
    case Z8_SPI_DR:
        sp->words_in++;
        return sp->dr;
    default:
        if (off < sizeof(sp->r)) {
            return sp->r[off / 4];
        }
        z8_stm32_stop("SPI", z8_stm32_spi_base[sp->inst] + off, size,
                       false, 0);
        return 0;
    }
}

/* How long one word takes on the wire: CR1.BR divides the bus clock by
 * 2^(BR+1), and CR1.DFF picks 8- or 16-bit frames (RM0386 28.5.1). SPI2
 * and SPI3 hang off APB1 (45 MHz here), the rest off APB2 (90 MHz). */
static int64_t z8_stm32_spi_word_ns(Z8Stm32Spi *sp)
{
    uint32_t cr1 = sp->r[Z8_SPI_CR1 / 4];
    uint64_t hz = (sp->inst == 1 || sp->inst == 2) ? 45000000 : 90000000;
    unsigned bits = (cr1 & (1u << 11)) ? 16 : 8;

    return (int64_t)bits * (2u << ((cr1 >> 3) & 7)) *
           NANOSECONDS_PER_SECOND / hz;
}

/*
 * A transmit by DMA to a listening device (sp->sink). On the part, TXE
 * with CR2.TXDMAEN is a request, and the stream answers it as fast as the
 * shift register empties; here the words armed when the transfer starts
 * leave together, once the time they would take has passed -- so the
 * stream's TC, and whatever the firmware does on it (chip select back
 * down), come when they would. Only an SPI with a sink does this: the
 * link's SPI1/SPI4 are clocked by the board (z8_mcu_link_pump).
 */
static void z8_stm32_spi_tx_dma(Z8Stm32Spi *sp)
{
    uint32_t par = z8_stm32_spi_base[sp->inst] + Z8_SPI_DR;

    if (!sp->sink || sp->tx_owed ||
        !(sp->r[Z8_SPI_CR1 / 4] & 0x40) ||           /* SPE */
        !(sp->r[Z8_SPI_CR2 / 4] & 0x02)) {           /* TXDMAEN */
        return;
    }
    sp->tx_owed = z8_stm32_dma_left(sp->mcu, par, true);
    if (sp->tx_owed) {
        timer_mod(sp->tx_timer, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) +
                  sp->tx_owed * z8_stm32_spi_word_ns(sp));
    }
}

static void z8_stm32_spi_tx_done(void *opaque)
{
    Z8Stm32Spi *sp = opaque;
    uint32_t par = z8_stm32_spi_base[sp->inst] + Z8_SPI_DR;
    uint32_t v;

    /* Still enabled? A firmware that stops the stream or the SPI early
     * gets only the words it let go. */
    while (sp->tx_owed && (sp->r[Z8_SPI_CR1 / 4] & 0x40) &&
           (sp->r[Z8_SPI_CR2 / 4] & 0x02) &&
           z8_stm32_dma_tx(sp->mcu, par, &v)) {
        sp->tx_owed--;
        sp->words_out++;
        sp->sink(sp->sink_opaque, sp->inst, v);
    }
    sp->tx_owed = 0;
    z8_stm32_spi_tx_dma(sp);                       /* a circular stream */
}

static void z8_stm32_spi_write(void *opaque, hwaddr off, uint64_t value,
                                unsigned size)
{
    Z8Stm32Spi *sp = opaque;

    z8_stm32_spi_note(sp, off, true);

    if (off == Z8_SPI_DR) {
        /* One word out, one word in: the peer clocks the exchange. With no
         * peer the bus is unconnected, and an unconnected MISO reads 0. */
        sp->words_out++;
        if (sp->sink) {
            sp->sink(sp->sink_opaque, sp->inst, value);
        }
        sp->dr = sp->peer ? sp->peer(sp->peer_opaque, sp->inst, value) : 0;
        z8_stm32_spi_irq_update(sp);
        return;
    }
    if (off < sizeof(sp->r)) {
        bool was_on = sp->r[Z8_SPI_CR1 / 4] & 0x40;

        sp->r[off / 4] = value;
        if (off == Z8_SPI_CR1 && (value & 0x40) && !was_on) {
            /* Enabling the SPI raises a request line, as on the part; if a
             * stream is already armed for this instance, that is the moment
             * the link starts moving. */
            if (++sp->enables <= 4) {
                error_report("Z8_STM32: SPI%u enabled (CR1.SPE set) "
                             "pc=0x%08x%s", sp->inst + 1, z8_stm32_pc(),
                             sp->enables == 4 ? " (further enables not "
                             "named)" : "");
            }
            z8_stm32_dma_kick(sp->mcu);
        }
        z8_stm32_spi_tx_dma(sp);
        z8_stm32_spi_irq_update(sp);
        return;
    }
    z8_stm32_stop("SPI", z8_stm32_spi_base[sp->inst] + off, size, true,
                   value);
}

static const MemoryRegionOps z8_stm32_spi_ops = {
    .read = z8_stm32_spi_read,
    .write = z8_stm32_spi_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4 },
};

/* Wire a peer onto SPI `inst` (0 = SPI1, 3 = SPI4). The board calls this
 * from mcu-spi-peer=; nothing else in the model assumes a peer exists. */
static void z8_stm32_spi_peer(Z8Stm32 *m, unsigned inst,
                               uint16_t (*fn)(void *, unsigned, uint16_t),
                               void *opaque)
{
    if (inst >= Z8_STM32_SPI_N) {
        return;
    }
    m->spi[inst].peer = fn;
    m->spi[inst].peer_opaque = opaque;
}

/* Wire a listening device onto SPI `inst` (1 = SPI2). See sp->sink. */
static void z8_stm32_spi_sink(Z8Stm32 *m, unsigned inst,
                               void (*fn)(void *, unsigned, uint16_t),
                               void *opaque)
{
    if (inst >= Z8_STM32_SPI_N) {
        return;
    }
    m->spi[inst].sink = fn;
    m->spi[inst].sink_opaque = opaque;
}

/* USART1, USART2, USART3, UART4, UART5, USART6 (QEMU's stm32f2xx model).
 * The application programs USART1 first (pc 0x0804e292). */
static const hwaddr z8_stm32_usart_base[6] = {
    0x40011000, 0x40004400, 0x40004800, 0x40004c00, 0x40005000, 0x40011400,
};
static const int z8_stm32_usart_irq[6] = { 37, 38, 39, 52, 53, 71 };

/* RM0386 EXTI 0..22 to the NVIC, including RTC alarm 17 / wakeup 22. */
static const int z8_stm32_exti_irq[23] = {
    6, 7, 8, 9, 10, 23, 23, 23, 23, 23, 40, 40, 40, 40, 40, 40,
    1, 41, 42, 62, 76, 2, 3,
};

/* ------------------------------------------------------------------ */
/* DMA1/DMA2 (RM0386 section 9): two controllers, eight streams each.  */
/* ------------------------------------------------------------------ */
/*
 * Registers, flags and interrupts as the manual has them. A memory-to-
 * memory stream (DIR = 10) runs to completion the moment it is enabled.
 * A peripheral stream is armed and named once; nothing yet issues the
 * peripheral's requests, so it waits -- which says which peripheral the
 * image drives by DMA, the next thing to connect.
 */
typedef struct Z8Stm32Dma Z8Stm32Dma;

static const hwaddr z8_stm32_dma_base[2] = { 0x40026000, 0x40026400 };
static const int z8_stm32_dma_irqn[2][8] = {
    { 11, 12, 13, 14, 15, 16, 17, 47 },
    { 56, 57, 58, 59, 60, 68, 69, 70 },
};

/* Stream n's four flag bits sit at these positions in LISR/HISR. */
static unsigned z8_stm32_dma_shift(unsigned n)
{
    static const unsigned shift[4] = { 0, 6, 16, 22 };

    return shift[n & 3];
}

static void z8_stm32_dma_irq(Z8Stm32Dma *d, unsigned n)
{
    uint32_t flags = (d->isr[n >> 2] >> z8_stm32_dma_shift(n)) & 0x3d;
    uint32_t cr = d->s[n].cr;
    bool level = ((flags & (1u << 5)) && (cr & (1u << 4))) ||   /* TCIF  TCIE */
                 ((flags & (1u << 4)) && (cr & (1u << 3))) ||   /* HTIF  HTIE */
                 ((flags & (1u << 3)) && (cr & (1u << 2))) ||   /* TEIF  TEIE */
                 ((flags & (1u << 2)) && (cr & (1u << 1)));     /* DMEIF DMEIE */

    qemu_set_irq(d->s[n].irq, level);
}

static void z8_stm32_dma_m2m(Z8Stm32Dma *d, unsigned n)
{
    AddressSpace *as = cpu_get_address_space(CPU(d->mcu->armv7m.cpu), 0);
    unsigned psize = 1u << ((d->s[n].cr >> 11) & 3);
    uint32_t count = d->s[n].ndtr & 0xffff;
    g_autofree uint8_t *buf = g_malloc(count * psize ? count * psize : 1);

    if (count) {
        address_space_read(as, d->s[n].par, MEMTXATTRS_UNSPECIFIED, buf,
                           count * psize);
        address_space_write(as, d->s[n].m0ar, MEMTXATTRS_UNSPECIFIED, buf,
                            count * psize);
    }
    d->s[n].ndtr = 0;
    d->s[n].cr &= ~1u;
    d->isr[n >> 2] |= (1u << 5 | 1u << 4) << z8_stm32_dma_shift(n);
    z8_stm32_dma_irq(d, n);
}

/* One item between a peripheral and memory for stream n of controller d.
 * Peripheral and memory widths must match (the image's do); a mismatch
 * stops, as an unmodelled packing mode. */
static bool z8_stm32_dma_item(Z8Stm32Dma *d, unsigned n, bool to_periph,
                               uint32_t *value)
{
    AddressSpace *as = cpu_get_address_space(CPU(d->mcu->armv7m.cpu), 0);
    uint32_t cr = d->s[n].cr;
    unsigned psize = 1u << ((cr >> 11) & 3), msize = 1u << ((cr >> 13) & 3);
    uint8_t buf[4] = { 0 };

    if (psize != msize) {
        z8_stm32_stop("DMA packing", z8_stm32_dma_base[d->ctrl] + 0x10 +
                       0x18 * n, 4, true, cr);
        return false;
    }
    if (to_periph) {
        address_space_read(as, d->s[n].cur_m, MEMTXATTRS_UNSPECIFIED, buf,
                           msize);
        *value = ldl_le_p(buf) & (msize == 4 ? 0xffffffff
                                             : (1u << (8 * msize)) - 1);
    } else {
        stl_le_p(buf, *value);
        address_space_write(as, d->s[n].cur_m, MEMTXATTRS_UNSPECIFIED, buf,
                            msize);
    }
    if (cr & (1u << 10)) {                          /* MINC */
        d->s[n].cur_m += msize;
    }
    if (cr & (1u << 9)) {                           /* PINC */
        d->s[n].cur_p += psize;
    }
    d->s[n].ndtr--;
    if (d->s[n].ndtr == d->s[n].ndtr_init / 2) {
        d->isr[n >> 2] |= (1u << 4) << z8_stm32_dma_shift(n);   /* HTIF */
    }
    if (d->s[n].ndtr == 0) {
        d->isr[n >> 2] |= (1u << 5) << z8_stm32_dma_shift(n);   /* TCIF */
        if (cr & (1u << 8)) {                       /* CIRC: reload */
            d->s[n].ndtr = d->s[n].ndtr_init;
            d->s[n].cur_m = d->s[n].m0ar;
            d->s[n].cur_p = d->s[n].par;
        } else {
            d->s[n].cr &= ~1u;
        }
    }
    z8_stm32_dma_irq(d, n);
    return true;
}

static bool z8_stm32_dma_serve(Z8Stm32 *m, uint32_t par, bool to_periph,
                                uint32_t *value)
{
    for (unsigned c = 0; c < 2; c++) {
        for (unsigned n = 0; n < 8; n++) {
            uint32_t cr = m->dma[c].s[n].cr;
            unsigned dir = (cr >> 6) & 3;

            if ((cr & 1) && m->dma[c].s[n].par == par && m->dma[c].s[n].ndtr &&
                dir == (to_periph ? 1 : 0)) {
                return z8_stm32_dma_item(&m->dma[c], n, to_periph, value);
            }
        }
    }
    return false;
}


static bool z8_stm32_dma_tx(Z8Stm32 *m, uint32_t par, uint32_t *value)
{
    return z8_stm32_dma_serve(m, par, true, value);
}

/* How wide the items of the stream armed on this register are, in bytes
 * (0 = nothing armed that way). The link needs it because the two chips
 * count differently: the EXPEED clocks 16-bit words, an 8-bit SPI on this
 * side moves one byte per frame, and the firmware's stream is sized for
 * the latter. */
static unsigned z8_stm32_dma_item_bytes(Z8Stm32 *m, uint32_t par,
                                         bool to_periph)
{
    for (unsigned c = 0; c < 2; c++) {
        for (unsigned n = 0; n < 8; n++) {
            uint32_t cr = m->dma[c].s[n].cr;

            if ((cr & 1) && m->dma[c].s[n].par == par &&
                m->dma[c].s[n].ndtr &&
                ((cr >> 6) & 3) == (to_periph ? 1 : 0)) {
                return 1u << ((cr >> 11) & 3);
            }
        }
    }
    return 0;
}

static bool z8_stm32_dma_rx(Z8Stm32 *m, uint32_t par, uint32_t value)
{
    return z8_stm32_dma_serve(m, par, false, &value);
}

/* Items still to move on the stream armed on this register (0 = none). */
static uint32_t z8_stm32_dma_left(Z8Stm32 *m, uint32_t par, bool to_periph)
{
    for (unsigned c = 0; c < 2; c++) {
        for (unsigned n = 0; n < 8; n++) {
            uint32_t cr = m->dma[c].s[n].cr;

            if ((cr & 1) && m->dma[c].s[n].par == par &&
                ((cr >> 6) & 3) == (to_periph ? 1 : 0)) {
                return m->dma[c].s[n].ndtr & 0xffff;
            }
        }
    }
    return 0;
}

/* A stream was enabled: a peripheral may already be requesting. */
static void z8_stm32_dma_kick(Z8Stm32 *m)
{
    if (m->stop_active) { return; }
    for (unsigned i = 0; i < 3; i++) {
        z8_stm32_i2c_pump(&m->i2c[i]);
    }
    z8_stm32_fmpi2c_step(m);
    z8_stm32_fmpi2c_irq(m);
    for (unsigned i = 0; i < Z8_STM32_SPI_N; i++) {
        z8_stm32_spi_tx_dma(&m->spi[i]);
    }
    /* And whatever the board has wired to a stream -- the SPI-to-serial
     * link, if mcu-spi-peer= bridged one. See z8_stm32_dma_item_bytes(). */
    if (m->link_kick) {
        m->link_kick(m->link_kick_opaque);
    }
}

static uint64_t z8_stm32_dma_read(void *opaque, hwaddr off, unsigned size)
{
    Z8Stm32Dma *d = opaque;
    unsigned n, reg;

    if (size != 4) {
        goto bad;
    }
    if (off < 0x10) {
        return off < 0x08 ? d->isr[off / 4] : 0;        /* IFCRs read 0 */
    }
    if (off >= 0xd0) {
        goto bad;
    }
    n = (off - 0x10) / 0x18;
    reg = (off - 0x10) % 0x18;
    switch (reg) {
    case 0x00: return d->s[n].cr;
    case 0x04: return d->s[n].ndtr;
    case 0x08: return d->s[n].par;
    case 0x0c: return d->s[n].m0ar;
    case 0x10: return d->s[n].m1ar;
    case 0x14: return d->s[n].fcr | 0x20;               /* FEMPTY-ish FS=100 */
    }
bad:
    z8_stm32_stop("DMA", z8_stm32_dma_base[d->ctrl] + off, size, false, 0);
    return 0;
}

static void z8_stm32_dma_write(void *opaque, hwaddr off, uint64_t value,
                                unsigned size)
{
    Z8Stm32Dma *d = opaque;
    unsigned n, reg;

    if (size != 4) {
        goto bad;
    }
    if (off < 0x10) {
        if (off >= 0x08) {                              /* LIFCR/HIFCR */
            d->isr[(off - 0x08) / 4] &= ~(value & 0x0f7d0f7d);
            for (n = 0; n < 8; n++) {
                z8_stm32_dma_irq(d, n);
            }
            return;
        }
        goto bad;                                       /* ISRs are RO */
    }
    if (off >= 0xd0) {
        goto bad;
    }
    n = (off - 0x10) / 0x18;
    reg = (off - 0x10) % 0x18;
    switch (reg) {
    case 0x00: {
        bool was_on = d->s[n].cr & 1;

        d->s[n].cr = value;
        if ((value & 1) && !was_on) {
            unsigned dir = (value >> 6) & 3;

            d->s[n].cur_m = (value & (1u << 19)) ? d->s[n].m1ar : d->s[n].m0ar;
            d->s[n].cur_p = d->s[n].par;
            d->s[n].ndtr_init = d->s[n].ndtr;
            if (dir == 2) {
                z8_stm32_dma_m2m(d, n);
            } else if (!d->s[n].named) {
                d->s[n].named = true;
                error_report("Z8_STM32: DMA%u stream %u armed: channel %u, "
                             "%s, peripheral 0x%08x, memory 0x%08x, %u items "
                             "(pc=0x%08x)",
                             d->ctrl + 1, n, (unsigned)(value >> 25) & 7,
                             dir == 1 ? "memory->peripheral"
                                      : "peripheral->memory",
                             d->s[n].par, d->s[n].m0ar, d->s[n].ndtr & 0xffff,
                             z8_stm32_pc());
            }
            if (dir != 2) {
                z8_stm32_dma_irq(d, n);
                z8_stm32_dma_kick(d->mcu);     /* a request may be pending */
                return;
            }
        }
        z8_stm32_dma_irq(d, n);
        return;
    }
    case 0x04: d->s[n].ndtr = value & 0xffff; return;
    case 0x08: d->s[n].par = value; return;
    case 0x0c: d->s[n].m0ar = value; return;
    case 0x10: d->s[n].m1ar = value; return;
    case 0x14: d->s[n].fcr = value & 0x87; return;
    }
bad:
    z8_stm32_stop("DMA", z8_stm32_dma_base[d->ctrl] + off, size, true,
                   value);
}

static const MemoryRegionOps z8_stm32_dma_ops = {
    .read = z8_stm32_dma_read,
    .write = z8_stm32_dma_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4 },
};

static void z8_stm32_dma_reset(Z8Stm32Dma *d)
{
    d->isr[0] = d->isr[1] = 0;
    for (unsigned n = 0; n < 8; n++) {
        d->s[n].cr = d->s[n].ndtr = d->s[n].par = 0;
        d->s[n].m0ar = d->s[n].m1ar = 0;
        d->s[n].fcr = 0x21;
    }
}

/* ------------------------------------------------------------------ */
/* ADC1..3 and the common block (RM0386 section 13).                   */
/* ------------------------------------------------------------------ */
/*
 * Software-started conversions only. A regular conversion converts the
 * first channel of the sequence (SQR3[4:0]) into DR; an injected one fills
 * JDR1..4 from JSQR. The level of every channel is a declared input,
 * mid-scale (0x800 of 12 bits) unless set -- not a measured voltage. DMA
 * and scan of a longer sequence are named once and not modelled.
 */
#define Z8_STM32_ADC_BASE 0x40012000ULL
#define Z8_ADC_SR    0x00
#define Z8_ADC_CR1   0x04
#define Z8_ADC_CR2   0x08
#define Z8_ADC_SQR3  0x34
#define Z8_ADC_JSQR  0x38
#define Z8_ADC_DR    0x4c

static void z8_stm32_adc_irq(Z8Stm32 *m)
{
    bool level = false;

    for (unsigned i = 0; i < 3; i++) {
        uint32_t sr = m->adc.r[i][Z8_ADC_SR / 4];
        uint32_t cr1 = m->adc.r[i][Z8_ADC_CR1 / 4];

        level |= ((sr & 2) && (cr1 & (1u << 5))) ||     /* EOC  EOCIE */
                 ((sr & 4) && (cr1 & (1u << 7)));       /* JEOC JEOCIE */
    }
    qemu_set_irq(m->adc.irq, level);
}

static uint64_t z8_stm32_adc_read(void *opaque, hwaddr off, unsigned size)
{
    Z8Stm32 *m = opaque;
    unsigned i = off / 0x100, reg = off % 0x100;

    if (size != 4) {
        goto bad;
    }
    if (off == 0x300) {                 /* CSR: the three SRs side by side */
        return (m->adc.r[0][0] & 0x3f) | (m->adc.r[1][0] & 0x3f) << 8 |
               (m->adc.r[2][0] & 0x3f) << 16;
    }
    if (off == 0x304) {
        return m->adc.ccr;
    }
    if (i < 3 && reg <= Z8_ADC_DR) {
        uint32_t v = m->adc.r[i][reg / 4];

        if (reg == Z8_ADC_DR) {
            m->adc.r[i][Z8_ADC_SR / 4] &= ~2u;         /* reading DR: EOC */
            z8_stm32_adc_irq(m);
        }
        return v;
    }
bad:
    z8_stm32_stop("ADC", Z8_STM32_ADC_BASE + off, size, false, 0);
    return 0;
}

static void z8_stm32_adc_write(void *opaque, hwaddr off, uint64_t value,
                                unsigned size)
{
    Z8Stm32 *m = opaque;
    unsigned i = off / 0x100, reg = off % 0x100;
    uint32_t *r;

    if (size != 4) {
        goto bad;
    }
    if (off == 0x304) {
        m->adc.ccr = value;
        return;
    }
    if (i >= 3 || reg > Z8_ADC_DR || reg == Z8_ADC_DR ||
        (reg >= 0x3c && reg <= 0x48)) {             /* JDRx, DR: read-only */
        goto bad;
    }
    r = m->adc.r[i];
    if (reg == Z8_ADC_SR) {                        /* rc_w0 */
        r[0] &= value | ~0x1fu;
        z8_stm32_adc_irq(m);
        return;
    }
    r[reg / 4] = value & ~((1u << 30) | (1u << 22));    /* SWSTART JSWSTART */
    if (reg == Z8_ADC_CR2 && (value & 1)) {
        if ((value & (1u << 8)) && !m->adc.dma_named) {
            m->adc.dma_named = true;
            error_report("Z8_STM32: ADC%u in DMA mode (pc=0x%08x) -- not "
                         "modelled", i + 1, z8_stm32_pc());
        }
        if (value & (1u << 30)) {                   /* regular conversion */
            unsigned ch = r[Z8_ADC_SQR3 / 4] & 0x1f;

            r[Z8_ADC_DR / 4] = ch < 19 ? m->adc.input[i][ch] : 0;
            r[0] |= 2 | (1u << 4);                  /* EOC STRT */
        }
        if (value & (1u << 22)) {                   /* injected conversion */
            uint32_t jsqr = r[Z8_ADC_JSQR / 4];
            unsigned n = ((jsqr >> 20) & 3) + 1;

            for (unsigned k = 0; k < n; k++) {
                unsigned ch = (jsqr >> (5 * (4 - n + k))) & 0x1f;

                r[(0x3c + 4 * k) / 4] = ch < 19 ? m->adc.input[i][ch] : 0;
            }
            r[0] |= 4 | (1u << 3);                  /* JEOC JSTRT */
        }
    }
    z8_stm32_adc_irq(m);
    return;
bad:
    z8_stm32_stop("ADC", Z8_STM32_ADC_BASE + off, size, true, value);
}

static const MemoryRegionOps z8_stm32_adc_ops = {
    .read = z8_stm32_adc_read,
    .write = z8_stm32_adc_write,
    .endianness = DEVICE_LITTLE_ENDIAN,
    .valid = { .min_access_size = 1, .max_access_size = 4 },
};

/* ------------------------------------------------------------------ */
/* Assembly.                                                           */
/* ------------------------------------------------------------------ */

static void z8_stm32_reset_registers(Z8Stm32 *m, bool power_on)
{
    uint32_t bdcr = m->rcc[Z8_RCC_BDCR / 4];
    uint32_t flags = m->rcc[0x74 / 4] & 0xfe000000;

    z8_stm32_rcc_reset(m);
    if (power_on) {
        z8_stm32_rtc_reset(m);
    } else {
        /* RM0386 6.1.1: system reset preserves the backup domain and
         * accumulated reset flags. SYSRESETREQ adds SFTRSTF, not PORRSTF.
         * Keep the live RTC/calendar and backup SRAM, not a host-time copy.
         */
        m->rcc[Z8_RCC_BDCR / 4] = bdcr;
        m->rcc[0x74 / 4] = flags | (1u << 28);
    }
    m->pwr_cr = 0x0000c000;             /* VOS scale 1 */
    m->pwr_csr = 0;
    m->flash_acr = 0;
    m->flash_sr = 0;
    m->flash_cr = 1u << 31;             /* LOCK */
    m->flash_optcr = 0x0fffaaed;
    m->flash_optcr1 = 0x0fff0000;
    m->flash_key = 0;
    for (unsigned i = 0; i < Z8_STM32_GPIO_PORTS; i++) {
        uint16_t outputs = m->gpio[i].odr;

        z8_stm32_gpio_reset(&m->gpio[i]);
        if (m->pin_out) {
            for (unsigned bit = 0; bit < 16; bit++) {
                if (outputs & (1u << bit)) {
                    m->pin_out(m->pin_out_opaque, i, bit, false);
                }
            }
        }
    }
    for (unsigned i = 0; i < 3; i++) {
        z8_stm32_i2c_reset(&m->i2c[i]);
        m->i2c[i].dev = NULL;
        m->i2c[i].last_sent = m->i2c[i].sh_full = m->i2c[i].reading = false;
        m->i2c[i].sh = m->i2c[i].dr = m->i2c[i].addr = 0;
    }
    memset(m->syscfg, 0, sizeof(m->syscfg));
    memset(m->adc.r, 0, sizeof(m->adc.r));
    m->adc.ccr = 0;
    z8_stm32_dma_reset(&m->dma[0]);
    z8_stm32_dma_reset(&m->dma[1]);
    for (unsigned c = 0; c < 2; c++) {
        for (unsigned n = 0; n < 8; n++) {
            m->dma[c].s[n].cur_m = m->dma[c].s[n].cur_p = 0;
            m->dma[c].s[n].ndtr_init = 0;
        }
    }
    for (unsigned i = 0; i < Z8_STM32_SPI_N; i++) {
        Z8Stm32Spi *spi = &m->spi[i];

        timer_del(spi->tx_timer);
        memset(spi->r, 0, sizeof(spi->r));
        spi->r[0x10 / 4] = 7;      /* CRCPR */
        spi->r[0x20 / 4] = 2;      /* I2SPR */
        spi->dr = spi->tx_owed = 0;
    }
    m->fmpi2c.cr1 = m->fmpi2c.cr2 = m->fmpi2c.oar1 = m->fmpi2c.oar2 = 0;
    m->fmpi2c.timingr = m->fmpi2c.timeoutr = 0;
    m->fmpi2c.isr = Z8_FMP_ISR_TXE;
    m->fmpi2c.dev = NULL;
    m->fmpi2c.left = m->fmpi2c.rxdr = 0;
    m->shutter.dir = 0;
    m->shutter.driven_ns = 0;
}

static void z8_stm32_reset(void *opaque)
{
    Z8Stm32 *m = opaque;
    if (m->stop_active) {
        m->stop_active = false;
        z8_stm32_stop_clocks(m, false);
    }
    m->stop_entries = m->stop_wakes = 0;
    z8_stm32_reset_registers(m, true);
}

/* This is the STM32 chip's system-reset domain, not an EXPEED reset.
 * Queue it on the M4 CPU: resetting its core/NVIC while it is still inside
 * the AIRCR write would destroy the active execution context. All QEMU
 * device updates below run with the BQL; no firmware address is special.
 */
static void z8_stm32_stop_clocks(Z8Stm32 *m, bool stopped)
{
    SysTickState *tick = &m->armv7m.systick[M_REG_NS];
    if (stopped) {
        m->stop_systick_run = (tick->control & 1) && ptimer_get_limit(tick->ptimer);
        ptimer_transaction_begin(tick->ptimer);
        ptimer_stop(tick->ptimer);
        ptimer_transaction_commit(tick->ptimer);
    }
    clock_update_hz(m->sysclk, stopped ? 0 : Z8_STM32_SYSCLK_HZ);
    if (!stopped && m->stop_systick_run) {
        ptimer_transaction_begin(tick->ptimer);
        ptimer_run(tick->ptimer, 0);
        ptimer_transaction_commit(tick->ptimer);
    }
    for (unsigned i = 0; i < ARRAY_SIZE(m->spi); i++) {
        QEMUTimer *timer = m->spi[i].tx_timer;
        if (!timer) { continue; }
        if (stopped) {
            m->stop_spi_deadline[i] = timer_expire_time_ns(timer);
            timer_del(timer);
        } else if (m->stop_spi_deadline[i] >= 0) {
            timer_mod(timer, m->stop_spi_deadline[i] +
                      qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) - m->stop_enter_ns);
        }
    }
    for (unsigned i = 0; i < ARRAY_SIZE(m->tim); i++) {
        stm32f2xx_timer_set_clock_stopped(&m->tim[i], stopped);
    }
    for (unsigned i = 0; i < ARRAY_SIZE(m->tim_more); i++) {
        stm32f2xx_timer_set_clock_stopped(&m->tim_more[i], stopped);
    }
}

static void z8_stm32_enter_stop(ARMCPU *cpu, bool wfe, void *opaque)
{
    Z8Stm32 *m = opaque;
    BQL_LOCK_GUARD();
    /* PDDS selects Standby, which is a separate reset/retention contract. */
    if (m->stop_active || (m->pwr_cr & 2)) {
        return;
    }
    m->stop_active = true;
    m->stop_wfe = wfe;
    m->stop_enter_ns = qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL);
    m->stop_entries++;
    z8_stm32_stop_clocks(m, true);
}

static void z8_stm32_leave_stop(Z8Stm32 *m)
{
    if (m->stop_active) {
        m->stop_active = false;
        m->stop_wakes++;
        z8_stm32_stop_clocks(m, false);
    }
}

static void z8_stm32_exti_interrupt(void *opaque, int line, int level)
{
    Z8Stm32 *m = opaque;
    if (level) {
        z8_stm32_leave_stop(m);
    }
    qemu_set_irq(qdev_get_gpio_in(DEVICE(&m->armv7m),
                 z8_stm32_exti_irq[line]), level);
}

static void z8_stm32_exti_event(void *opaque, int line, int level)
{
    Z8Stm32 *m = opaque;
    if (level) {
        if (m->stop_wfe) {
            z8_stm32_leave_stop(m);
        }
        m->armv7m.cpu->env.event_register = true;
        qemu_cpu_kick(CPU(m->armv7m.cpu));
    }
}

static void z8_stm32_system_reset_on_cpu(CPUState *cpu, run_on_cpu_data data)
{
    Z8Stm32 *m = data.host_ptr;

    assert(bql_locked());
    z8_stm32_leave_stop(m);
    z8_stm32_reset_registers(m, false);
    for (unsigned i = 0; i < ARRAY_SIZE(m->tim); i++) {
        device_cold_reset(DEVICE(&m->tim[i]));
    }
    for (unsigned i = 0; i < ARRAY_SIZE(m->tim_more); i++) {
        device_cold_reset(DEVICE(&m->tim_more[i]));
    }
    for (unsigned i = 0; i < ARRAY_SIZE(m->usart); i++) {
        device_cold_reset(DEVICE(&m->usart[i]));
    }
    for (unsigned i = 0; i < ARRAY_SIZE(m->tim_or); i++) {
        device_cold_reset(DEVICE(&m->tim_or[i]));
    }
    device_cold_reset(DEVICE(&m->exti));
    device_cold_reset(DEVICE(&m->armv7m.systick[M_REG_NS]));
    for (unsigned i = 0; i < Z8_STM32_NUM_IRQ; i++) {
        qemu_set_irq(qdev_get_gpio_in(DEVICE(&m->armv7m), i), 0);
    }
    device_cold_reset(DEVICE(&m->armv7m.nvic));
    cpu_reset(cpu);
    m->system_reset_pending = false;
    m->system_resets++;
    error_report("Z8_STM32_RESET: MCU system reset #%" PRIu64
                 "; EXPEED and external devices retained, no image reload",
                 m->system_resets);
}

static void z8_stm32_sysresetreq(void *opaque, int n, int level)
{
    Z8Stm32 *m = opaque;

    if (!level || m->system_reset_pending) {
        return;
    }
    m->system_reset_pending = true;
    async_run_on_cpu(CPU(m->armv7m.cpu), z8_stm32_system_reset_on_cpu,
                     RUN_ON_CPU_HOST_PTR(m));
}

static void z8_stm32_map(Z8Stm32 *m, MemoryRegion *mr, Object *owner,
                        const MemoryRegionOps *ops, void *opaque,
                        const char *name, hwaddr base, uint64_t size)
{
    memory_region_init_io(mr, owner, ops, opaque, name, size);
    memory_region_add_subregion(&m->mem, base, mr);
}

/* TEMPORARY PROBE (remove): print the core's PC and xPSR, the NVIC's
 * enabled-IRQ sets and its active bits every two seconds of virtual time,
 * plus the DMA streams' state. Answers "is it stuck, and on what". */
/* TEMPORARY PROBE (remove): read one peripheral register. */
static uint32_t z8_stm32_reg_read(AddressSpace *as, hwaddr addr)
{
    uint32_t v = 0;

    address_space_read(as, addr, MEMTXATTRS_UNSPECIFIED, &v, 4);
    return v;
}



/* Build the MCU and load its image (a raw dump of flash from 0x08000000).
 * The core starts at reset, from the vector table at 0 -- the flash alias,
 * BOOT0 low. */
/*
 * The shutter mechanism: a motor the MCU drives and the two position
 * sensors it reads back. The live-view start (and every mode change) waits
 * on it: the EXPEED's capture-sync request (pin 43, PF4 here) is answered
 * on PD7 only once the shutter has moved (sub_803B194 -> sub_803A820), and
 * without a mechanism the motor ran into its drive timeout at every
 * request and the EXPEED's mode-0 request never completed (error 0x35 on
 * the next one).
 *
 * What the firmware does, all on this image:
 *   - power: PA11 high before a move (sub_8042864's caller, byte 0x2001a407
 *     ticks of settling);
 *   - drive: TIM2, PWM mode 1 on CH1 (PA15, AF1) and CH3 (PB10, AF1), ARR
 *     0x897; sub_803AA48 puts the duty on one channel and 0 on the other,
 *     or 0 on both to stop. At the live-view start CCR1 = 0x1b8, CCR3 = 0,
 *     the move sub_8042B0C counts as +1: CH1 is forward;
 *   - sensors: PC6 and PC7 (AF2, TIM3 TI1 and TI2), read as a two-bit
 *     position through the table at 0x8058670 -- 0 HH, 1 LH, 2 LL, 3 HL,
 *     (PC6, PC7) -- a quadrature pair, one bit changing per step. The MCU
 *     arms an input capture on the sensor the next step will change
 *     (TIM3 CCMR1 0x101, CCER 0x121 for PC6 rising), debounces, re-reads
 *     the pins and steps its own count (sub_80421A0 -> sub_8042654).
 *     sub_8041C54 wants position 2, both low, before a move from closed.
 *
 * So: while the motor has power and one channel has duty, the shutter
 * advances one position per Z8_SHUTTER_STEP_NS of drive, forward on CH1
 * and back on CH3, and each step changes one sensor pin, which is an edge
 * on that TIM3 input (stm32f2xx_timer_input). It stops where it is when the
 * drive stops. DECLARED: the start at position 2 and the step time -- 10 ms,
 * inside the firmware's own drive timeout (~110 ms for a two-step move at
 * the live-view start); the duty is not modelled as speed, nor inertia,
 * bounce or the brake. A body would replace both numbers.
 */
#define Z8_SHUTTER_TICK_NS     (500 * SCALE_US)
#define Z8_SHUTTER_STEP_NS     (10 * SCALE_MS)
#define Z8_SHUTTER_START       2
#define Z8_SHUTTER_NAMED       24

static const uint8_t z8_shutter_pins[4] = {
    3, 2, 0, 1,         /* bit 0 PC6, bit 1 PC7: HH LH LL HL */
};

static void z8_stm32_shutter_pins(Z8Stm32 *m, bool edges)
{
    Z8Stm32Gpio *c = &m->gpio[2];

    for (unsigned b = 0; b < 2; b++) {
        bool level = (z8_shutter_pins[m->shutter.pos] >> b) & 1;

        if (edges && ((c->level >> (6 + b)) & 1) == level) {
            continue;
        }
        z8_stm32_gpio_drive(c, 6 + b, level);
        if (edges) {
            stm32f2xx_timer_input(&m->tim[1], b, level);   /* TIM3 TI1/2 */
        }
    }
}

static void z8_stm32_shutter_tick(void *opaque)
{
    Z8Stm32 *m = opaque;
    STM32F2XXTimerState *pwm = &m->tim[0];             /* TIM2 */
    bool run = (m->gpio[0].odr & (1u << 11)) &&         /* PA11 */
               (pwm->tim_cr1 & TIM_CR1_CEN);
    int dir = !run ? 0 :
              (pwm->tim_ccer & 0x001) && pwm->tim_ccr1 && !pwm->tim_ccr3 ? 1 :
              (pwm->tim_ccer & 0x100) && pwm->tim_ccr3 && !pwm->tim_ccr1 ? -1 :
              0;

    if (dir != m->shutter.dir) {
        m->shutter.dir = dir;
        m->shutter.driven_ns = 0;
        if (m->shutter.named < Z8_SHUTTER_NAMED) {
            m->shutter.named++;
            error_report("Z8_SHUTTER: motor %s at position %u (TIM2 CCR1 "
                         "%u, CCR3 %u)", dir > 0 ? "forward" :
                         dir < 0 ? "reverse" : "stopped", m->shutter.pos,
                         pwm->tim_ccr1, pwm->tim_ccr3);
        }
    }
    if (dir) {
        m->shutter.driven_ns += Z8_SHUTTER_TICK_NS;
        if (m->shutter.driven_ns >= Z8_SHUTTER_STEP_NS) {
            m->shutter.driven_ns = 0;
            m->shutter.pos = (m->shutter.pos + dir) & 3;
            m->shutter.steps++;
            z8_stm32_shutter_pins(m, true);
            if (m->shutter.named < Z8_SHUTTER_NAMED) {
                m->shutter.named++;
                error_report("Z8_SHUTTER: position %u (PC6 %u, PC7 %u), "
                             "step %" PRIu64, m->shutter.pos,
                             z8_shutter_pins[m->shutter.pos] & 1,
                             z8_shutter_pins[m->shutter.pos] >> 1,
                             m->shutter.steps);
            }
        }
    }
    timer_mod(m->shutter.timer,
              qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL) + Z8_SHUTTER_TICK_NS);
}

static void z8_stm32_init(Z8Stm32 *m, Object *owner, const char *image,
                           Chardev **serial, Error **errp)
{
    DeviceState *armv7m;
    Error *err = NULL;

    memory_region_init(&m->mem, owner, "z8-mcu", 0x100000000ULL);
    memory_region_init_io(&m->trap, owner, &z8_stm32_trap_ops, m,
                          "z8-mcu-trap", 0x100000000ULL);
    memory_region_add_subregion_overlap(&m->mem, 0, &m->trap, -1000);

    /* The owner is a machine, not a device: register the RAM globally. */
    memory_region_init_rom_device(&m->flash, NULL,
                                            &z8_stm32_flash_ops, m,
                                            "z8-mcu-flash",
                                            Z8_STM32_FLASH_SIZE, &err);
    if (err) {
        error_propagate(errp, err);
        return;
    }
    memory_region_add_subregion(&m->mem, Z8_STM32_FLASH_BASE, &m->flash);
    memory_region_init_alias(&m->flash_alias, owner, "z8-mcu-flash-alias",
                             &m->flash, 0, Z8_STM32_FLASH_SIZE);
    memory_region_add_subregion(&m->mem, 0, &m->flash_alias);
    memory_region_init_ram(&m->sram, NULL, "z8-mcu-sram",
                           Z8_STM32_SRAM_SIZE, &error_fatal);
    memory_region_add_subregion(&m->mem, Z8_STM32_SRAM_BASE, &m->sram);
    memory_region_init_ram(&m->ccm, NULL, "z8-mcu-ccm",
                           Z8_STM32_CCM_SIZE, &error_fatal);
    memory_region_add_subregion(&m->mem, Z8_STM32_CCM_BASE, &m->ccm);
    memory_region_init_ram(&m->bkpsram, NULL, "z8-mcu-bkpsram",
                           Z8_STM32_BKPSRAM_SIZE, &error_fatal);
    memory_region_add_subregion(&m->mem, Z8_STM32_BKPSRAM_BASE, &m->bkpsram);

    z8_stm32_map(m, &m->rcc_mr, owner, &z8_stm32_rcc_ops, m, "z8-mcu-rcc",
                Z8_STM32_RCC_BASE, 0x400);
    z8_stm32_map(m, &m->pwr_mr, owner, &z8_stm32_pwr_ops, m, "z8-mcu-pwr",
                Z8_STM32_PWR_BASE, 0x400);
    z8_stm32_map(m, &m->rtc_mr, owner, &z8_stm32_rtc_ops, m, "z8-mcu-rtc",
                Z8_STM32_RTC_BASE, 0x400);
    z8_stm32_map(m, &m->flashif_mr, owner, &z8_stm32_flashif_ops, m,
                "z8-mcu-flashif", Z8_STM32_FLASHIF_BASE, 0x400);
    for (unsigned i = 0; i < Z8_STM32_GPIO_PORTS; i++) {
        g_autofree char *name = g_strdup_printf("z8-mcu-gpio%c", 'a' + i);

        m->gpio[i].mcu = m;
        m->gpio[i].port = i;
        z8_stm32_map(m, &m->gpio[i].mr, owner, &z8_stm32_gpio_ops, &m->gpio[i],
                    name, Z8_STM32_GPIO_BASE + 0x400 * i, 0x400);
    }

    m->sysclk = clock_new(owner, "z8-mcu-sysclk");
    clock_set_hz(m->sysclk, Z8_STM32_SYSCLK_HZ);
    m->refclk = clock_new(owner, "z8-mcu-refclk");
    clock_set_mul_div(m->refclk, 8, 1);             /* HCLK / 8 */
    clock_set_source(m->refclk, m->sysclk);

    object_initialize_child(owner, "z8-mcu-cluster", &m->cluster,
                            TYPE_CPU_CLUSTER);
    qdev_prop_set_uint32(DEVICE(&m->cluster), "cluster-id", 1);
    object_initialize_child(OBJECT(&m->cluster), "z8-mcu-armv7m", &m->armv7m,
                            TYPE_ARMV7M);
    armv7m = DEVICE(&m->armv7m);
    qdev_prop_set_uint32(armv7m, "num-irq", Z8_STM32_NUM_IRQ);
    qdev_prop_set_uint8(armv7m, "num-prio-bits", 4);
    qdev_prop_set_string(armv7m, "cpu-type", ARM_CPU_TYPE_NAME("cortex-m4"));
    qdev_prop_set_bit(armv7m, "enable-bitband", true);
    qdev_connect_clock_in(armv7m, "cpuclk", m->sysclk);
    qdev_connect_clock_in(armv7m, "refclk", m->refclk);
    object_property_set_link(OBJECT(armv7m), "memory", OBJECT(&m->mem),
                             &error_abort);
    if (!sysbus_realize(SYS_BUS_DEVICE(armv7m), errp) ||
        !qdev_realize(DEVICE(&m->cluster), NULL, errp)) {
        return;
    }
    m->armv7m.cpu->m_profile_sleep = z8_stm32_enter_stop;
    m->armv7m.cpu->m_profile_sleep_opaque = m;
    m->sysresetreq = qemu_allocate_irq(z8_stm32_sysresetreq, m, 0);
    qdev_connect_gpio_out_named(armv7m, "SYSRESETREQ", 0, m->sysresetreq);

    for (unsigned i = 0; i < 4; i++) {
        g_autofree char *name = g_strdup_printf("z8-mcu-tim%u", i + 2);
        SysBusDevice *sbd;

        object_initialize_child(owner, name, &m->tim[i], TYPE_STM32F2XX_TIMER);
        /* See "ccr-wraps" in hw/timer/stm32f2xx_timer.c: the switch
         * service's first snapshot is a TIM10 match beyond ARR. */
        qdev_prop_set_bit(DEVICE(&m->tim[i]), "ccr-wraps", true);
        qdev_prop_set_uint64(DEVICE(&m->tim[i]), "clock-frequency",
                             Z8_STM32_TIM_HZ);
        sbd = SYS_BUS_DEVICE(&m->tim[i]);
        if (!sysbus_realize(sbd, errp)) {
            return;
        }
        memory_region_add_subregion(&m->mem, z8_stm32_tim_base[i],
                                    sysbus_mmio_get_region(sbd, 0));
        sysbus_connect_irq(sbd, 0, qdev_get_gpio_in(armv7m,
                                                    z8_stm32_tim_irq[i]));
    }

    for (unsigned i = 0; i < ARRAY_SIZE(m->i2c_dev); i++) {
        Z8Stm32I2cDev *d = &m->i2c_dev[i];

        d->bus = z8_stm32_i2c_dev_at[i].bus;
        d->addr = z8_stm32_i2c_dev_at[i].addr;
        for (unsigned e = 0; e < ARRAY_SIZE(z8_stm32_expander_at); e++) {
            if (d->bus == 3 && d->addr == z8_stm32_expander_at[e]) {
                d->expander = true;
                d->inputs = d->logged = 0xffffff; /* every button released */
            }
        }
    }
    for (unsigned i = 0; i < 3; i++) {
        g_autofree char *name = g_strdup_printf("z8-mcu-i2c%u", i + 1);
        Z8Stm32I2c *c = &m->i2c[i];

        c->mcu = m;
        c->bus = i;
        c->ev_irq = qdev_get_gpio_in(armv7m, z8_stm32_i2c_irqn[i][0]);
        c->er_irq = qdev_get_gpio_in(armv7m, z8_stm32_i2c_irqn[i][1]);
        z8_stm32_map(m, &c->mr, owner, &z8_stm32_i2c_ops, c, name,
                      z8_stm32_i2c_base[i], 0x400);
    }

    for (unsigned i = 0; i < 2; i++) {
        g_autofree char *name = g_strdup_printf("z8-mcu-tim-or%u", i);
        DeviceState *gate;

        object_initialize_child(owner, name, &m->tim_or[i], TYPE_OR_IRQ);
        gate = DEVICE(&m->tim_or[i]);
        object_property_set_int(OBJECT(gate), "num-lines", 2, &error_abort);
        if (!qdev_realize(gate, NULL, errp)) {
            return;
        }
        qdev_connect_gpio_out(gate, 0, qdev_get_gpio_in(armv7m,
                                                        i ? 44 : 25));
    }
    for (unsigned i = 0, shared[2] = { 0, 0 }; i < 10; i++) {
        g_autofree char *name = g_strdup_printf("z8-mcu-%s",
                                                z8_stm32_tim_more[i].name);
        int irq = z8_stm32_tim_more[i].irq;
        SysBusDevice *sbd;
        qemu_irq line;

        object_initialize_child(owner, name, &m->tim_more[i],
                                TYPE_STM32F2XX_TIMER);
        /* See "ccr-wraps" in hw/timer/stm32f2xx_timer.c: the switch
         * service's first snapshot is a TIM10 match beyond ARR. */
        qdev_prop_set_bit(DEVICE(&m->tim_more[i]), "ccr-wraps", true);
        qdev_prop_set_uint64(DEVICE(&m->tim_more[i]), "clock-frequency",
                             z8_stm32_tim_more[i].hz);
        sbd = SYS_BUS_DEVICE(&m->tim_more[i]);
        if (!sysbus_realize(sbd, errp)) {
            return;
        }
        memory_region_add_subregion(&m->mem, z8_stm32_tim_more[i].base,
                                    sysbus_mmio_get_region(sbd, 0));
        if (irq >= 0) {
            line = qdev_get_gpio_in(armv7m, irq);
        } else {
            unsigned g = -irq - 1;

            line = qdev_get_gpio_in(DEVICE(&m->tim_or[g]), shared[g]++);
        }
        sysbus_connect_irq(sbd, 0, line);
        if (z8_stm32_tim_more[i].cc) {
            sysbus_connect_irq(sbd, 1, qdev_get_gpio_in(armv7m,
                                               z8_stm32_tim_more[i].cc));
        }
    }

    /* serial[i], when given, is the host end of USART i (the standalone
     * machine passes -serial; the board none yet). */
    for (unsigned i = 0; i < 6; i++) {
        g_autofree char *name = g_strdup_printf("z8-mcu-usart%u", i + 1);
        SysBusDevice *sbd;

        object_initialize_child(owner, name, &m->usart[i],
                                TYPE_STM32F2XX_USART);
        if (serial && serial[i]) {
            qdev_prop_set_chr(DEVICE(&m->usart[i]), "chardev", serial[i]);
        }
        sbd = SYS_BUS_DEVICE(&m->usart[i]);
        if (!sysbus_realize(sbd, errp)) {
            return;
        }
        memory_region_add_subregion(&m->mem, z8_stm32_usart_base[i],
                                    sysbus_mmio_get_region(sbd, 0));
        sysbus_connect_irq(sbd, 0, qdev_get_gpio_in(armv7m,
                                                    z8_stm32_usart_irq[i]));
    }

    /* SYSCFG routes GPIO pins to EXTI lines (z8_stm32_gpio_drive); EXTI,
     * QEMU's model, raises the NVIC. */
    z8_stm32_map(m, &m->syscfg_mr, owner, &z8_stm32_syscfg_ops, m,
                  "z8-mcu-syscfg", Z8_STM32_SYSCFG_BASE, 0x400);
    for (unsigned i = 0; i < Z8_STM32_SPI_N; i++) {
        g_autofree char *name = g_strdup_printf("z8-mcu-spi%u", i + 1);

        m->spi[i].mcu = m;
        m->spi[i].inst = i;
        /* The M4's NVIC input line *is* the qemu_irq, as for USART above. */
        m->spi[i].irq = qdev_get_gpio_in(armv7m, z8_stm32_spi_irq[i]);
        m->spi[i].tx_timer = timer_new_ns(QEMU_CLOCK_VIRTUAL,
                                          z8_stm32_spi_tx_done, &m->spi[i]);
        z8_stm32_map(m, &m->spi[i].mr, owner, &z8_stm32_spi_ops,
                      &m->spi[i], name, z8_stm32_spi_base[i], 0x400);
    }
    object_initialize_child(owner, "z8-mcu-exti", &m->exti,
                            TYPE_STM32F4XX_EXTI);
    if (!sysbus_realize(SYS_BUS_DEVICE(&m->exti), errp)) {
        return;
    }
    memory_region_add_subregion(&m->mem, 0x40013c00,
        sysbus_mmio_get_region(SYS_BUS_DEVICE(&m->exti), 0));
    for (unsigned i = 0; i < 23; i++) {
        m->exti_irq[i] = qemu_allocate_irq(z8_stm32_exti_interrupt, m, i);
        sysbus_connect_irq(SYS_BUS_DEVICE(&m->exti), i, m->exti_irq[i]);
    }

    for (unsigned c = 0; c < 2; c++) {
        g_autofree char *name = g_strdup_printf("z8-mcu-dma%u", c + 1);
        Z8Stm32Dma *d = &m->dma[c];

        d->mcu = m;
        d->ctrl = c;
        for (unsigned n = 0; n < 8; n++) {
            d->s[n].irq = qdev_get_gpio_in(armv7m, z8_stm32_dma_irqn[c][n]);
        }
        z8_stm32_map(m, &d->mr, owner, &z8_stm32_dma_ops, d, name,
                      z8_stm32_dma_base[c], 0x400);
    }

    for (unsigned i = 0; i < 3; i++) {
        for (unsigned ch = 0; ch < 19; ch++) {
            m->adc.input[i][ch] = 0x800;
        }
    }
    m->adc.irq = qdev_get_gpio_in(armv7m, 18);
    z8_stm32_map(m, &m->adc.mr, owner, &z8_stm32_adc_ops, m, "z8-mcu-adc",
                  Z8_STM32_ADC_BASE, 0x400);

    m->flash_irq = qdev_get_gpio_in(armv7m, 4);
    m->fmpi2c.ev_irq = qdev_get_gpio_in(armv7m, 95);
    m->fmpi2c.er_irq = qdev_get_gpio_in(armv7m, 96);
    z8_stm32_map(m, &m->fmpi2c.mr, owner, &z8_stm32_fmpi2c_ops, m,
                  "z8-mcu-fmpi2c1", Z8_STM32_FMPI2C_BASE, 0x400);

    m->exti_event = qemu_allocate_irq(z8_stm32_exti_event, m, 0);
    qdev_connect_gpio_out_named(DEVICE(&m->exti), "event", 0, m->exti_event);

    m->rtc_alarm_timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, z8_stm32_rtc_alarm_tick, m);
    m->rtc_wake_timer = timer_new_ns(QEMU_CLOCK_VIRTUAL, z8_stm32_rtc_wake_tick, m);

    z8_stm32_reset(m);
    qemu_register_reset(z8_stm32_reset, m);

    /* The shutter keeps its position through an MCU reset; it is a
     * mechanism, not a register. */
    m->shutter.pos = Z8_SHUTTER_START;
    /* Z6III shutter position wiring is not applied to Z8 by default. */
    m->shutter.timer = timer_new_ns(QEMU_CLOCK_VIRTUAL,
                                    z8_stm32_shutter_tick, m);
    /* The inherited virtual mechanism remains unarmed pending Z8 wiring. */

    armv7m_load_kernel(m->armv7m.cpu, image, Z8_STM32_FLASH_BASE,
                       Z8_STM32_FLASH_SIZE);
    error_report("Z8_STM32: STM32F469-class MCU running '%s' (fixed 180 MHz, "
                 "ready bits follow enables; see nikon-z8-stm32.h)", image);
}

#endif /* HW_ARM_NIKON_Z8_STM32_H */
