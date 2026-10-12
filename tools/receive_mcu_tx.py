# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Diagnostic MCU peer reading native channel 0 TX through its PIO FIFO.

GPIO ready/ack are retained levels with explicit IRQ57 pulses; this is not a
physical GPIO implementation. No guest CPU or RAM values are replaced.
"""
import json
import struct

from probe_adc_capture import at
from probe_graphics_image import save
from observe_serial_channel import at_channel


def receive(g, *, prefix):
    record = dict(prefix=prefix, stages=[], complete=False)
    g.data.setdefault('frame_outputs', []).append(record)
    children = g.qmp.command('qom-list', path='/machine/unattached')
    gics = [child for child in children if child['type'] == 'child<arm-gicv3>']
    if len(gics) != 1:
        raise RuntimeError('cannot identify unique modeled GIC')
    path = '/machine/unattached/' + gics[0]['name']
    names = {item['name'] for item in g.qmp.command('qom-list', path=path)}
    if 'unnamed-gpio-in[25]' not in names:
        raise RuntimeError('expected IRQ57 input absent')

    def pulse():
        g.qt_command(f'set_irq_in {path} unnamed-gpio-in 25 1')
        try:
            cpu, regs = at(g, 0x40c161d8)
            record['stages'].append(dict(name='original_gpio_tx_isr', cpu=cpu, registers=regs))
        finally:
            g.qt_command(f'set_irq_in {path} unnamed-gpio-in 25 0')

    def state():
        return json.loads(g.qmp.command('qom-get', path='/machine', property='serial-state'))[0]

    record['gpio_before'] = dict(ready=g.rd(0xd15100c), ack=g.rd(0xd151010))
    g.wr(0xd151010, g.rd(0xd151010) & ~8)
    g.wr(0xd15100c, g.rd(0xd15100c) | 4)
    pulse()
    cpu, regs = at(g, 0x40c930ec)
    descriptor = save(g, prefix + 'request', regs['X01'], 0x20)
    tx, rx = struct.unpack_from('<QQ', descriptor)
    record['stages'].append(dict(name='original_tx_request', cpu=cpu, registers=regs,
                                 descriptor_hex=descriptor.hex()))
    g.check(prefix + 'native TX requests serial channel 0', regs['X00'] == 0)
    expected = save(g, prefix + 'buffer', tx, 256)
    cpu, regs = at_channel(g, 0x40c14a8c, 0, record)
    initial = state()
    record['stages'].append(dict(name='native_pio_prefill', cpu=cpu, registers=regs, serial=initial))
    g.check(prefix + 'native TX PIO prefill', initial['pio_active'] and initial['tx_queued'] == 64)
    g.wr(0xd15100c, g.rd(0xd15100c) & ~4)
    g.qmp.command('qom-set', path='/machine', property='serial-clock', value='0:' + bytes(128).hex())
    wire = bytes.fromhex(g.qmp.command('qom-get', path='/machine', property='serial-last-tx'))
    cpu, regs = at_channel(g, 0x40c14ad0, 0, record)
    middle = state()
    record['stages'].append(dict(name='native_pio_refill', cpu=cpu, registers=regs, serial=middle))
    g.check(prefix + 'native TX refills second chunk', middle['read'] == 64 and middle['tx_queued'] == 64)
    g.qmp.command('qom-set', path='/machine', property='serial-clock', value='0:' + bytes(128).hex())
    wire += bytes.fromhex(g.qmp.command('qom-get', path='/machine', property='serial-last-tx'))
    (g.out / (prefix + 'wire.bin')).write_bytes(wire)
    record['frame_hex'] = wire.hex()
    g.check(prefix + 'native TX wire matches original buffer and checksum', wire == expected and sum(wire) & 255 == 255)
    cpu, regs = at(g, 0x40c930f0)
    record['stages'].append(dict(name='native_serial_return', cpu=cpu, registers=regs, serial=state()))
    g.check(prefix + 'native serial transfer succeeds', regs['X00'] == 0)
    g.wr(0xd151010, g.rd(0xd151010) | 8)
    pulse()
    cpu, regs = at(g, 0x40c931d8)
    record['stages'].append(dict(name='native_tx_ack_read', cpu=cpu, registers=regs))
    g.check(prefix + 'native driver reads MCU ack high', regs['X00'] == 1)
    at(g, 0x40c93240)
    g.wr(0xd151010, g.rd(0xd151010) & ~8)
    record['complete'] = True
    return wire
