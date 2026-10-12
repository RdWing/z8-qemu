# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Diagnostic external frame delivery through the native Z8 PIO RX path.

Uses a retained GPIO level and one explicit GIC pulse per frame. This is a
transport diagnostic, not a physical GPIO or complete MCU peer model.
"""
import json
import struct

from probe_adc_capture import at
from probe_graphics_image import save as save_capture
from observe_serial_channel import at_channel


def deliver(g, frame, *, prefix='', bindings=None):
    if len(frame) != 256:
        raise ValueError('one complete 256-byte transport frame required')
    record = dict(frame_hex=frame.hex(), prefix=prefix, stages=[], mcu_protocol_accepted=False)
    g.data.setdefault('frame_inputs', []).append(record)
    original = dict(gpio_rx_isr=0x40c161f0,rx_request=0x40c934b4,
        serial_before_enable=0x40c14a60,serial_prefill=0x40c14a8c,
        serial_drain=0x40c14ad0,serial_rx_isr=0x40c14f10,rx_accepted=0x40c935c8)
    points = original if bindings is None else bindings
    record['instruction_bindings'] = {k:hex(points[k]) for k in original}

    def save(guest, label, address, size):
        return save_capture(guest, prefix + label, address, size)

    record['gpio_before'] = {hex(address): g.rd(address) for address in
                            (0x0d15100c, 0x0c86e000, 0x0c86e004, 0x0c86e008,
                             0x0c86e014, 0x0c86e018)}
    children = g.qmp.command('qom-list', path='/machine/unattached')
    gics = [child for child in children if child['type'] == 'child<arm-gicv3>']
    if len(gics) != 1:
        raise RuntimeError('cannot identify unique modeled GIC')
    gic_path = '/machine/unattached/' + gics[0]['name']
    gpio_names = {item['name'] for item in g.qmp.command('qom-list', path=gic_path)}
    if f'unnamed-gpio-in[{0x3a-32}]' not in gpio_names:
        raise RuntimeError('expected GIC input is absent; do not call unsafe qtest setter')
    g.wr(0x0d15100c, record['gpio_before']['0xd15100c'] | 8)
    g.qt_command(f'set_irq_in {gic_path} unnamed-gpio-in {0x3a-32} 1')
    record['gic_after_pulse']={hex(a):g.rd(a) for a in [0xd000000,0xd000084,0xd000104,0xd000204,0xd0061d0,0xd0061d4]}
    try:
        cpu, registers = at(g, points['gpio_rx_isr'])
        record['stages'].append(dict(name='original_gpio_rx_isr', cpu=cpu, registers=registers))
    finally:
        g.qt_command(f'set_irq_in {gic_path} unnamed-gpio-in {0x3a-32} 0')
    cpu, registers = at(g, points['rx_request'])
    descriptor = save(g, 'rx-request', registers['X01'], 0x20)
    tx, rx = struct.unpack_from('<QQ', descriptor)
    record['stages'].append(dict(name='original_rx_request', cpu=cpu, registers=registers,
                                 descriptor_hex=descriptor.hex()))
    g.check('original MCU receive requests serial channel 1', registers['X00'] == 1)
    def serial_state():
        return json.loads(g.qmp.command('qom-get', path='/machine', property='serial-state'))[1]

    def channel_point(pc):
        return at_channel(g, pc, 1, record, bindings=bindings)

    cpu, registers = channel_point(points['serial_before_enable'])
    record['serial_configuration'] = {hex(offset): g.rd(0xe700100 + offset)
                                       for offset in (0xc, 0x10, 0x20, 0x3c, 0x4c, 0x64)}
    record['serial_before_enable'] = serial_state()
    cpu, registers = channel_point(points['serial_prefill'])
    initial = serial_state()
    record['stages'].append(dict(name='native_pio_prefill', cpu=cpu, registers=registers,
                                 serial=initial))
    g.check('original channel 1 prefills 64 PIO words',
            initial['pio_active'] and initial['tx_queued'] == 64 and initial['rx_queued'] == 0)
    expected_tx = save(g, 'tx-before', tx, 256)
    save(g, 'rx-before', rx, 256)
    g.qmp.command('qom-set', path='/machine', property='serial-clock', value='1:' + frame[:128].hex())
    actual_tx = bytes.fromhex(g.qmp.command('qom-get', path='/machine', property='serial-last-tx'))
    cpu, registers = at(g, points['serial_rx_isr'])
    record['stages'].append(dict(name='native_pio_rx_isr', cpu=cpu, registers=registers,
                                 serial=serial_state()))
    cpu, registers = channel_point(points['serial_drain'])
    middle = serial_state()
    record['stages'].append(dict(name='native_pio_drain_and_refill', cpu=cpu, registers=registers,
                                 serial=middle))
    g.check('native task drains first chunk and refills TX',
            middle['read'] == 64 and middle['tx_queued'] == 64 and middle['rx_queued'] == 0)
    g.check('native PIO writes first RX chunk', g.read_bytes(rx, 128) == frame[:128])
    g.qmp.command('qom-set', path='/machine', property='serial-clock', value='1:' + frame[128:].hex())
    actual_tx += bytes.fromhex(g.qmp.command('qom-get', path='/machine', property='serial-last-tx'))
    (g.out / (prefix + 'serial-tx.bin')).write_bytes(actual_tx)
    g.check('external clock sees native TX bytes in order', actual_tx == expected_tx)
    # Release the external ready level after the complete diagnostic frame.
    g.wr(0x0d15100c, record['gpio_before']['0xd15100c'])
    cpu, registers = at(g, points['rx_accepted'])
    record['stages'].append(dict(name='native_transport_frame_accepted', cpu=cpu, registers=registers))
    actual = save(g, 'rx-after', rx, 256)
    g.check('serial RX RAM contains complete supplied frame', actual == frame)
    record['mcu_protocol_accepted'] = True
    return record
