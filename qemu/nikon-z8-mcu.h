/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Copyright (C) 2026 RdWing */
/* Original EX firmware owns messages. The board only connects GPIO, SPI
 * and DMA. Pin bindings here are Z8 C3.11/EX03.00 static/probe bindings;
 * clocks, battery and top-panel ready timing remain functional fixtures. */
#include "chardev/char.h"
#include "nikon-z8-mcu-adc.h"
typedef struct Z8McuBridge Z8McuBridge;
typedef struct Z8McuLink {
    Z8McuBridge *bridge;
    unsigned spi, channel, at;
    uint8_t frame[2][256], last[2][256];
    uint64_t words, frames[2], bad_frames[2];
} Z8McuLink;
struct Z8McuBridge {
    NikonZ8State *owner;
    Z8Stm32 chip;
    Z8TopLcd panel;
    Z8McuLink link[2];
    QEMUTimer *timer;
    qemu_irq irq[3];
    bool pumping;
    DeviceState *main_gic;
    unsigned supply_port, supply_pin;
    bool supply_enabled, supply_armed, supply_off;
    uint64_t supply_cuts, supply_resets;
    uint8_t switch_report[124], switch_wire[256];
    uint64_t switch_frames;
};

static void z8_mcu_gpio_update(NikonZ8State *s)
{
    if (!s->native_mcu) { return; }
    uint32_t pending=s->gpio_irq_config[0][2]&~s->gpio_irq_config[0][0];
    for (unsigned i=0;i<2;i++) { qemu_set_irq(s->native_mcu->irq[i],!!(pending&(4u<<i))); }
    qemu_set_irq(s->native_mcu->irq[2],s->mcu_capture_sync_wires && !!(pending&0x80));
}
static uint32_t z8_mcu_gpio_read(NikonZ8State *s, hwaddr addr, uint32_t value)
{
    Z8McuBridge *m=s->native_mcu;
    if (!m) { return value; }
    /* RX-ready PB14, TX-ready PE3, receive-validator ACK PD12. */
    const unsigned pins[4][4]={{1,14,3,2},{4,3,3,3},{3,12,4,3},{3,7,3,7}};
    for (unsigned i=0;i<(s->mcu_capture_sync_wires ? 4 : 3);i++) {
        const unsigned *p=pins[i];
        if (addr==0x0d151000+4*p[2] && ((m->chip.gpio[p[0]].moder>>(2*p[1]))&3)==1) {
            value=(value&~(1u<<p[3]))|(((m->chip.gpio[p[0]].odr>>p[1])&1)<<p[3]);
        }
    }
    return value;
}
static uint32_t z8_mcu_gpio_write(NikonZ8State *s, hwaddr addr, uint32_t value)
{
    if (!s->native_mcu || (addr!=0x0d15100c && addr!=0x0d151010)) { return value; }
    uint32_t old=s->syscon[(addr-0x0d150000)/4], mask=value>>16;
    uint32_t next=(old&~mask)|(value&mask);
    if (addr==0x0d15100c && (mask&0x1000) && ((old^next)&0x1000)) {
        fprintf(stderr,"Z8_NATIVE_REQUEST ns=%"PRId64" level=%u pc=%"PRIx64"; MAIN port3 bit12\n",
            qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL),!!(next&0x1000),
            current_cpu ? ARM_CPU(current_cpu)->env.pc : 0);
    }
    /* Explicit candidate wire only: MAIN drives an EX peripheral input.
     * EX firmware/EXTI owns any PD7 reply; no timer or synthetic ACK here. */
    if (s->mcu_capture_sync_wires && addr==0x0d15100c && (mask&0x1000)) {
        z8_stm32_gpio_drive(&s->native_mcu->chip.gpio[5],4,!!(next&0x1000));
    }
    if (addr==0x0d151010 && (mask&0x80)) {
        z8_stm32_gpio_drive(&s->native_mcu->chip.gpio[6],6,!!(next&0x80));
    }
    return z8_mcu_gpio_read(s,addr,next);
}
/* Explicit virtual supply, not an asserted physical pin-to-rail binding.
 * The initial fixture is powered. First high arms subsequent cut/return edges. */
static void z8_mcu_main_supply(Z8McuBridge *m, bool level)
{
    if (!m->supply_enabled) { return; }
    if (level && !m->supply_armed) { m->supply_armed = true; return; }
    if (!level && m->supply_armed && !m->supply_off) {
        m->supply_off = true; m->supply_cuts++;
        CPUState *cs;
        CPU_FOREACH(cs) {
            ARMCPU *cpu = ARM_CPU(cs);
            if (!arm_feature(&cpu->env, ARM_FEATURE_M)) {
                arm_set_cpu_off(arm_cpu_mp_affinity(cpu));
            }
        }
        error_report("Z8_MAIN_SUPPLY cut ns=%"PRId64, qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL));
    } else if (level && m->supply_off) {
        m->supply_off = false; m->supply_resets++;
        device_cold_reset(m->main_gic);
        int rc = arm_set_cpu_on_and_reset(0);
        error_report("Z8_MAIN_SUPPLY return ns=%"PRId64" architectural reset rc=%d; EX/card/RAM retained",
                     qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL), rc);
    }
}

static void z8_mcu_pin_out(void *opaque,unsigned port,unsigned pin,bool level)
{
    Z8McuBridge *m=opaque;NikonZ8State *s=m->owner;
    if (port==m->supply_port && pin==m->supply_pin &&
        ((m->chip.gpio[port].moder >> (2*pin)) & 3) == 1) {
        z8_mcu_main_supply(m,level);
    }
    if (port==0 && pin==4) { z8_toplcd_scs(&m->panel,level); }
    if (port==4 && pin==8) { z8_toplcd_disp(&m->panel,level); }
    if (port==3 && pin==11) { z8_toplcd_start(&m->panel,level); }
    if (port==3 && pin==7) {
        fprintf(stderr,"Z8_NATIVE_PD7 ns=%"PRId64" level=%u; original EX output\n",
            qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL),level);
    }
    unsigned bit=port==1 && pin==14 ? 2 : port==4 && pin==3 ? 3 :
                 s->mcu_capture_sync_wires && port==3 && pin==7 ? 7 : 32;
    if (bit<32) {
        uint32_t old=s->syscon[0x100c/4], flag=1u<<bit;
        s->syscon[0x100c/4]=(old&~flag)|(level ? flag : 0);
        if (!!(old&flag)!=level && !!(s->gpio_irq_config[0][5]&flag)==level &&
            (s->gpio_irq_config[0][6]&flag)) { s->gpio_irq_config[0][2]|=flag; }
        z8_mcu_gpio_update(s);
    }
    if (port==3 && pin==12) {
        s->syscon[0x1010/4]=(s->syscon[0x1010/4]&~8u)|(level ? 8 : 0);
    }
}
static bool z8_mcu_exchange(Z8McuLink *l,uint16_t input,uint16_t *output)
{
    NikonZ8State *s=l->bridge->owner;Z8SerialPIO *p=&s->serial_pio[l->channel];
    if (!p->active || !p->tx_queued || p->rx_queued>=64) { return false; }
    if (p->word_bits!=16) { unknown_access(s,0x0e700000+0x100*l->channel,input,4,true);return false; }
    *output=p->tx[p->tx_head];p->tx_head=(p->tx_head+1)%64;p->tx_queued--;
    p->rx[(p->rx_head+p->rx_queued)%64]=input;p->rx_queued++;p->clocked++;
    serial_pio_update(s,l->channel);
    l->frame[0][l->at*2]=*output;l->frame[0][l->at*2+1]=*output>>8;
    l->frame[1][l->at*2]=input;l->frame[1][l->at*2+1]=input>>8;
    l->words++;
    if (++l->at==128) {
        l->at=0;
        for (unsigned dir=0;dir<2;dir++) {
            uint8_t *f=l->frame[dir];unsigned sum=0;
            memcpy(l->last[dir],f,256);
            if (!f[0]) { continue; }
            for (unsigned i=0;i<256;i++) { sum+=f[i]; }
            l->frames[dir]++;l->bad_frames[dir]+=(sum&255)!=255;
            if (f[0]==9) {
                fprintf(stderr,"Z8_NATIVE_COMMAND ns=%"PRId64" SPI%u %s length=%u type=%u selector=%x argument=%x checksum=%s\n",
                    qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL),l->spi+1,dir ? "MCU->MAIN" : "MAIN->MCU",
                    lduw_le_p(f+2),ldl_le_p(f+8),ldl_le_p(f+12),ldl_le_p(f+16),(sum&255)==255 ? "ok" : "BAD");
            }
            if (l->channel==1 && dir==1 && (sum&255)==255 && f[0]==2 &&
                lduw_le_p(f+2)==124 && f[8]==1) {
                memcpy(l->bridge->switch_report,f+8,124);memcpy(l->bridge->switch_wire,f,256);l->bridge->switch_frames++;
            }
            if (l->frames[dir]<=8) {
                fprintf(stderr,"Z8_NATIVE_MCU SPI%u %s family=%u kind=%u length=%u checksum=%s\n",
                    l->spi+1,dir ? "MCU->MAIN" : "MAIN->MCU",f[0],f[8],lduw_le_p(f+2),(sum&255)==255 ? "ok" : "BAD");
            }
        }
    }
    return true;
}
static uint16_t z8_mcu_cpu_peer(void *opaque,unsigned inst,uint16_t out)
{
    Z8McuLink *l=opaque;uint16_t in=0;(void)inst;
    z8_mcu_exchange(l,out,&in);return in;
}
static void z8_mcu_link_pump(Z8McuLink *l)
{
    Z8McuBridge *m=l->bridge;Z8Stm32 *chip=&m->chip;
    uint32_t par=z8_stm32_spi_base[l->spi]+0xc;
    Z8SerialPIO *p=&m->owner->serial_pio[l->channel];
    if (!(chip->spi[l->spi].r[0]&0x40)) { return; }
    for (unsigned budget=0;budget<64 && p->active && p->tx_queued && p->rx_queued<64;budget++) {
        uint32_t v=0;unsigned items=z8_stm32_dma_item_bytes(chip,par,true);
        if (items) {
            if (!z8_stm32_dma_tx(chip,par,&v)) { break; }
            if (items==1) { uint32_t hi=0;if (!z8_stm32_dma_tx(chip,par,&hi)) { break; }v|=(hi&255)<<8; }
        }
        uint16_t in=0;if (!z8_mcu_exchange(l,v,&in)) { break; }
        items=z8_stm32_dma_item_bytes(chip,par,false);
        if (items==1) { z8_stm32_dma_rx(chip,par,in&255);z8_stm32_dma_rx(chip,par,in>>8); }
        else if (items) { z8_stm32_dma_rx(chip,par,in); }
    }
}
static void z8_mcu_tick(void *opaque)
{
    Z8McuBridge *m=opaque;
    if (m->pumping) { return; }
    m->pumping=true;
    for (unsigned i=0;i<2;i++) { z8_mcu_link_pump(&m->link[i]); }
    m->pumping=false;
}
static void z8_mcu_schedule(NikonZ8State *s,unsigned ch)
{
    if (s->native_mcu && ch<2 && !timer_pending(s->native_mcu->timer)) {
        timer_mod(s->native_mcu->timer,qemu_clock_get_ns(QEMU_CLOCK_VIRTUAL)+1000);
    }
}
static void z8_mcu_kick(void *opaque) { z8_mcu_schedule(((Z8McuBridge *)opaque)->owner,0); }
static bool z8_mcu_apply_contacts(Z8McuBridge *m,const char *value,Error **errp);
static void z8_mcu_init(NikonZ8State *s,DeviceState *gic)
{
    if (!s->mcu_image || !*s->mcu_image) {
        if (s->mcu_main_supply_pin) { error_report("mcu-main-supply-pin requires native MCU attachment");exit(1); }
        if (s->mcu_adc_inputs) { error_report("mcu-adc-inputs requires native MCU attachment");exit(1); }
        if (s->mcu_capture_sync_wires) { error_report("mcu-capture-sync-wires requires original EX attachment");exit(1); }
        return;
    }
    if (MACHINE(s)->smp.max_cpus<5 || !s->serial_fixture || s->ccomp_gpio_model) {
        error_report("native MCU requires -smp 4,maxcpus=5, serial-fixture and no synthetic CCOMP GPIO peer");exit(1);
    }
    Z8McuBridge *m=g_new0(Z8McuBridge,1);m->owner=s;s->native_mcu=m;
    m->main_gic = gic;
    if (s->mcu_main_supply_pin) {
        m->supply_enabled = true;
        m->supply_port = s->mcu_main_supply_pin[0] - 'A';
        m->supply_pin = atoi(s->mcu_main_supply_pin + 1);
    }
    for (unsigned i=0;i<2;i++) { m->irq[i]=qdev_get_gpio_in(gic,25+i); }
    m->irq[2]=qdev_get_gpio_in(gic,30);
    m->timer=timer_new_ns(QEMU_CLOCK_VIRTUAL,z8_mcu_tick,m);
    /* Optional named character backends expose the six existing STM32
     * register instances separately. No Z63 pin/console role is assigned. */
    Chardev *serial[6];
    for (unsigned i=0;i<ARRAY_SIZE(serial);i++) {
        g_autofree char *name=g_strdup_printf("z8-ex-usart%u",i+1);
        serial[i]=qemu_chr_find(name);
    }
    z8_stm32_init(&m->chip,OBJECT(s),s->mcu_image,serial,&error_fatal);
    if (s->mcu_adc_inputs && !z8_adc_inputs(m->chip.adc.input,s->mcu_adc_inputs)) { error_report("Invalid retained MCU ADC inputs");exit(1); }
    z8_stm32_rtc_option(&m->chip,"2026-01-02T03:04:05",&error_fatal);
    /* Z8 EX03.00 panel initializer requests pin ID 1 (PA1), not
     * the Z63 reference ID 49 (PD1). Ready timing is still declared. */
    z8_toplcd_init(&m->panel,NULL,&m->chip.gpio[0],1);
    m->chip.pin_out=z8_mcu_pin_out;m->chip.pin_out_opaque=m;
    m->chip.link_kick=z8_mcu_kick;m->chip.link_kick_opaque=m;
    for (unsigned i=0;i<2;i++) {
        Z8McuLink *l=&m->link[i];l->bridge=m;l->channel=i;l->spi=i ? 3 : 0;
        m->chip.spi[l->spi].peer=z8_mcu_cpu_peer;m->chip.spi[l->spi].peer_opaque=l;
    }
    m->chip.spi[1].sink=z8_toplcd_byte;m->chip.spi[1].sink_opaque=&m->panel;
    z8_stm32_gpio_drive(&m->chip.gpio[3],13,true); /* explicit virtual battery idle */
    if (s->mcu_capture_sync_wires) { z8_stm32_gpio_drive(&m->chip.gpio[5],4,!!(s->syscon[0x100c/4]&0x1000)); }
    z8_stm32_pins(&m->chip,s->mcu_pins,&error_fatal);
    z8_mcu_apply_contacts(m,s->mcu_contacts,&error_fatal);
}
static char *get_z8_main_supply(Object *obj,Error **errp)
{ return g_strdup(NIKON_Z8_LAB(obj)->mcu_main_supply_pin); }
static void set_z8_main_supply(Object *obj,const char *value,Error **errp)
{
    char port, tail; unsigned pin;
    if (!value || strlen(value)<2 || strlen(value)>3 ||
        sscanf(value, "%c%u%c", &port, &pin, &tail) != 2 ||
        port < 'A' || port > 'K' || pin > 15) {
        error_setg(errp, "mcu-main-supply-pin requires one declared pin A0..K15"); return;
    }
    NikonZ8State *s=NIKON_Z8_LAB(obj);
    g_free(s->mcu_main_supply_pin); s->mcu_main_supply_pin=g_strdup(value);
}
static char *get_z8_mcu_image(Object *obj,Error **errp) { return g_strdup(NIKON_Z8_LAB(obj)->mcu_image); }
static void set_z8_mcu_image(Object *obj,const char *value,Error **errp)
{
    NikonZ8State *s=NIKON_Z8_LAB(obj);
    if (s->image_ram.ram || s->image_ram.rom_device) { error_setg(errp,"MCU image immutable after realization");return; }
    g_free(s->mcu_image);s->mcu_image=g_strdup(value);
}
static char *get_z8_mcu_state(Object *obj,Error **errp)
{
    Z8McuBridge *m=NIKON_Z8_LAB(obj)->native_mcu;
    if (!m) { return g_strdup("{\"enabled\":false}"); }
    return g_strdup_printf("{\"enabled\":true,\"host_message_replies\":false,\"pc\":%u,\"system_resets\":%"PRIu64
        ",\"main_tx_words\":%"PRIu64",\"main_rx_words\":%"PRIu64",\"main_frames\":%"PRIu64",\"mcu_frames\":%"PRIu64
        ",\"bad_frames\":%"PRIu64",\"panel_packets\":%"PRIu64",\"panel_lines\":%"PRIu64",\"physical_wiring_verified\":false}",
        m->chip.armv7m.cpu->env.regs[15],m->chip.system_resets,m->link[0].words,m->link[1].words,
        m->link[0].frames[0],m->link[1].frames[1],m->link[0].bad_frames[0]+m->link[1].bad_frames[1],m->panel.packets,m->panel.lines);
}
/* Read state directly: diagnostic sampling must not clear peripheral status. */
static char *get_z8_mcu_io(Object *obj,Error **errp)
{
    NikonZ8State *s=NIKON_Z8_LAB(obj);Z8McuBridge *m=s->native_mcu;
    if (!m) { return g_strdup("{\"enabled\":false}"); }
    GString *out=g_string_new(NULL);
    g_string_append_printf(out,"{\"enabled\":true,\"main_gpio\":{\"port3\":%u,\"port4\":%u,\"mask\":%u,\"pending\":%u,\"polarity\":%u,\"enable\":%u},\"exti\":{\"mask\":%u,\"rising\":%u,\"falling\":%u,\"pending\":%u},\"routes\":[%u,%u,%u,%u],\"gpio\":[",
        s->syscon[0x100c/4],s->syscon[0x1010/4],s->gpio_irq_config[0][0],s->gpio_irq_config[0][2],s->gpio_irq_config[0][5],s->gpio_irq_config[0][6],
        m->chip.exti.exti_imr,m->chip.exti.exti_rtsr,m->chip.exti.exti_ftsr,m->chip.exti.exti_pr,
        m->chip.syscfg[2],m->chip.syscfg[3],m->chip.syscfg[4],m->chip.syscfg[5]);
    for (unsigned i=0;i<Z8_STM32_GPIO_PORTS;i++) {
        Z8Stm32Gpio *g=&m->chip.gpio[i];
        g_string_append_printf(out,"%s{\"port\":%u,\"mode\":%u,\"pull\":%u,\"input\":%u,\"output\":%u,\"driven\":%u}",
            i ? "," : "",i,g->moder,g->pupdr,z8_stm32_gpio_idr(g),g->odr,g->driven);
    }
    g_string_append(out,"],\"serial\":[");
    for (unsigned i=0;i<2;i++) {
        Z8SerialPIO *p=&s->serial_pio[i];
        g_string_append_printf(out,"%s{\"channel\":%u,\"active\":%s,\"tx_queued\":%u,\"rx_queued\":%u,\"pending\":%u,\"mcu_cr1\":%u,\"mcu_cr2\":%u}",
            i ? "," : "",i,p->active ? "true" : "false",p->tx_queued,p->rx_queued,p->pending,
            m->chip.spi[i ? 3 : 0].r[0],m->chip.spi[i ? 3 : 0].r[1]);
    }
    g_string_append_printf(out,"],\"main_supply\":{\"enabled\":%s,\"armed\":%s,\"off\":%s,\"cuts\":%"PRIu64",\"resets\":%"PRIu64"},\"power\":{\"stop_active\":%s,\"stop_entries\":%"PRIu64",\"stop_wakes\":%"PRIu64"},\"rtc\":{\"control\":%u,\"stored_status\":%u,\"prescaler\":%u,\"wakeup_reload\":%u,\"alarm_a\":%u,\"alarm_b\":%u,\"alarm_subseconds_a\":%u,\"alarm_subseconds_b\":%u,\"backup_clock\":%u,\"alarm_matches\":[%"PRIu64",%"PRIu64"],\"wakeup_expiries\":%"PRIu64",\"alarm_irq_level\":%s,\"wakeup_irq_level\":%s}}",
        m->supply_enabled ? "true" : "false",m->supply_armed ? "true" : "false",m->supply_off ? "true" : "false",m->supply_cuts,m->supply_resets,
        m->chip.stop_active ? "true" : "false",m->chip.stop_entries,m->chip.stop_wakes,
        m->chip.rtc[2],m->chip.rtc[3],m->chip.rtc[4],m->chip.rtc[5],
        m->chip.rtc[7],m->chip.rtc[8],m->chip.rtc[17],m->chip.rtc[18],
        m->chip.rcc[Z8_RCC_BDCR/4],m->chip.rtc_alarm_events[0],m->chip.rtc_alarm_events[1],m->chip.rtc_wake_events,
        m->chip.rtc_alarm_level ? "true" : "false",m->chip.rtc_wake_level ? "true" : "false");
    return g_string_free(out,false);
}
static char *get_z8_mcu_toplcd(Object *obj,Error **errp)
{
    Z8McuBridge *m=NIKON_Z8_LAB(obj)->native_mcu;GString *out=g_string_new(NULL);
    if (m) { for (unsigned i=0;i<sizeof(m->panel.mem);i++) { g_string_append_printf(out,"%02x",((uint8_t *)m->panel.mem)[i]); } }
    return g_string_free(out,false);
}

/* Raw external contacts are useful before a Z8 button-name map is qualified.
 * This property drives peripheral inputs only, never firmware RAM/PC/results. */
static char *get_z8_mcu_pins(Object *obj, Error **errp)
{
    return g_strdup(NIKON_Z8_LAB(obj)->mcu_pins);
}
static void set_z8_mcu_pins(Object *obj, const char *value, Error **errp)
{
    NikonZ8State *s=NIKON_Z8_LAB(obj);
    if (s->native_mcu && !z8_stm32_pins(&s->native_mcu->chip,value,errp)) { return; }
    g_free(s->mcu_pins);s->mcu_pins=g_strdup(value);
}
static char *get_z8_mcu_wire(Object *obj,Error **errp)
{
    Z8McuBridge *m=NIKON_Z8_LAB(obj)->native_mcu;
    GString *out=g_string_new("[");
    if (m) {
        for (unsigned i=0;i<2;i++) {
            for (unsigned dir=0;dir<2;dir++) {
                if (i||dir) { g_string_append_c(out,','); }
                g_string_append_printf(out,"{\"channel\":%u,\"direction\":\"%s\",\"frame_hex\":\"",i,dir ? "mcu_to_main" : "main_to_mcu");
                for (unsigned b=0;b<256;b++) { g_string_append_printf(out,"%02x",m->link[i].last[dir][b]); }
                g_string_append(out,"\"}");
            }
        }
    }
    g_string_append_c(out,']');return g_string_free(out,false);
}

static bool z8_mcu_apply_contacts(Z8McuBridge *m,const char *value,Error **errp)
{
    if (value && strlen(value)>1024) { error_setg(errp,"MCU contact input too long");return false; }
    g_auto(GStrv) items=g_strsplit_set(value ? value : "",":",-1);
    for (char **it=items;*it;it++) {
        unsigned addr,bit,level;char tail;
        if (!**it) { continue; }
        if (sscanf(*it,"%x.%u=%u%c",&addr,&bit,&level,&tail)!=3 ||
            (addr!=0x22 && addr!=0x23) || bit>23 || level>1) {
            error_setg(errp,"MCU contact '%s': expected 22/23.<bit 0..23>=<level 0/1>",*it);return false;
        }
    }
    for (char **it=items;*it;it++) {
        unsigned addr,bit,level;
        if (!**it) { continue; }
        sscanf(*it,"%x.%u=%u",&addr,&bit,&level);
        if (!z8_stm32_expander_set(&m->chip,addr,bit,!level)) {
            error_setg(errp,"MCU contact expander not realized");return false;
        }
    }
    return true;
}
static char *get_z8_mcu_contacts(Object *obj,Error **errp)
{
    return g_strdup(NIKON_Z8_LAB(obj)->mcu_contacts);
}
static void set_z8_mcu_contacts(Object *obj,const char *value,Error **errp)
{
    NikonZ8State *s=NIKON_Z8_LAB(obj);
    if (s->native_mcu && !z8_mcu_apply_contacts(s->native_mcu,value,errp)) { return; }
    g_free(s->mcu_contacts);s->mcu_contacts=g_strdup(value);
}
static char *get_z8_mcu_switches(Object *obj,Error **errp)
{
    Z8McuBridge *m=NIKON_Z8_LAB(obj)->native_mcu;
    if (!m) { return g_strdup("{\"enabled\":false}"); }
    GString *out=g_string_new(NULL);
    g_string_append_printf(out,"{\"enabled\":true,\"frames\":%"PRIu64",\"report_hex\":\"",m->switch_frames);
    for (unsigned i=0;i<124;i++) { g_string_append_printf(out,"%02x",m->switch_report[i]); }
    g_string_append(out,"\",\"frame_hex\":\"");
    for (unsigned i=0;i<256;i++) { g_string_append_printf(out,"%02x",m->switch_wire[i]); }
    g_string_append(out,"\",\"expanders\":[");unsigned count=0;
    for (unsigned i=0;i<ARRAY_SIZE(m->chip.i2c_dev);i++) {
        struct Z8Stm32I2cDev *d=&m->chip.i2c_dev[i];
        if (!d->expander) { continue; }
        g_string_append_printf(out,"%s{\"address\":%u,\"inputs\":%u}",count++ ? "," : "",d->addr,d->inputs);
    }
    g_string_append(out,"]}");return g_string_free(out,false);
}


static bool get_z8_mcu_capture_sync_wires(Object *obj, Error **errp)
{
    return NIKON_Z8_LAB(obj)->mcu_capture_sync_wires;
}
static void set_z8_mcu_capture_sync_wires(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s=NIKON_Z8_LAB(obj);
    if (s->native_mcu || s->image_ram.ram || s->image_ram.rom_device) { error_setg(errp,"mcu-capture-sync-wires is immutable after realization");return; }
    s->mcu_capture_sync_wires=value;
}

/* Explicit external analog samples. Input updates do not convert or set IRQs. */
static char *get_z8_mcu_adc_inputs(Object *obj, Error **errp)
{
    return g_strdup(NIKON_Z8_LAB(obj)->mcu_adc_inputs ?: "");
}
static void set_z8_mcu_adc_inputs(Object *obj, const char *value, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    uint16_t next[3][19] = { { 0 } };
    if (s->native_mcu) { memcpy(next,s->native_mcu->chip.adc.input,sizeof(next)); }
    if (!z8_adc_inputs(next, value) ||
        (!s->native_mcu && (s->image_ram.ram || s->image_ram.rom_device))) {
        error_setg(errp,"mcu-adc-inputs requires native MCU and ADC.CH=VALUE batches; ADC 1..3, CH 0..18, VALUE 0..4095, no duplicates");return;
    }
    if (s->native_mcu) { memcpy(s->native_mcu->chip.adc.input,next,sizeof(next)); }
    char *copy=g_strdup(value);g_free(s->mcu_adc_inputs);s->mcu_adc_inputs=copy;
}
static char *get_z8_mcu_adc_state(Object *obj, Error **errp)
{
    Z8McuBridge *m = NIKON_Z8_LAB(obj)->native_mcu;
    if (!m) { return g_strdup("{\"enabled\":false}"); }
    GString *out=g_string_new("{\"enabled\":true,\"physical_units_verified\":false,\"adcs\":[");
    for (unsigned i=0;i<3;i++) {
        g_string_append_printf(out,"%s{\"adc\":%u,\"inputs\":[",i ? "," : "",i+1);
        for (unsigned ch=0;ch<19;ch++) { g_string_append_printf(out,"%s%u",ch ? "," : "",m->chip.adc.input[i][ch]); }
        g_string_append_printf(out,"],\"status\":%u,\"data\":%u,\"injected\":[%u,%u,%u,%u]}",m->chip.adc.r[i][0],m->chip.adc.r[i][Z8_ADC_DR/4],
            m->chip.adc.r[i][0x3c/4],m->chip.adc.r[i][0x40/4],m->chip.adc.r[i][0x44/4],m->chip.adc.r[i][0x48/4]);
    }
    g_string_append(out,"]}");return g_string_free(out,false);
}

/* Panel observations read model memory, never status-clearing MMIO. */
static char *get_z8_mcu_panel_state(Object *obj, Error **errp)
{
    Z8McuBridge *m=NIKON_Z8_LAB(obj)->native_mcu;
    if (!m) { return g_strdup("{\"enabled\":false}"); }
    Z8TopLcd *t=&m->panel;
    return g_strdup_printf("{\"enabled\":true,\"width\":144,\"height\":168,\"scs\":%s,\"display_on\":%s,"
        "\"packets\":%"PRIu64",\"lines\":%"PRIu64",\"clears\":%"PRIu64",\"ready_port\":%u,\"ready_pin\":%u,"
        "\"ready_level\":%u,\"ready_pending\":%s,\"ready_delay_ns\":%u,\"physical_timing_verified\":false}",
        t->scs ? "true" : "false",t->disp ? "true" : "false",t->packets,t->lines,t->clears,t->ready_gpio->port,t->ready_pin,
        !!(z8_stm32_gpio_idr(t->ready_gpio)&(1u<<t->ready_pin)),timer_pending(t->ready_timer) ? "true" : "false",(unsigned)Z8_TOPLCD_READY_NS);
}
