# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Explicit clock for observed channel-8/9 PIO writes.

This supplies dummy RX only to complete a physical full-duplex exchange. The
original request must discard those bytes; channel 9 RX requires an explicit
candidate switch and remains unverified on hardware. No invented device ID, status,
sensor data, protocol-success response, guest RAM edit or completion patch.
"""
import json
from pathlib import Path
import struct

from probe import sha
from probe_graphics_image import save


class WritePeer:
    def __init__(self, g, continuation=False, *, channel=8, wire_bits=8,
                 object_base=0xa02808780, allow_dummy_rx=False):
        if (channel,wire_bits) not in ((8,8),(9,9)):
            raise ValueError('only observed channel8/8bit or channel9/9bit PIO contracts')
        self.g = g
        self.channel,self.wire_bits,self.object_base=channel,wire_bits,object_base
        self.allow_dummy_rx=allow_dummy_rx
        key=f'serial{channel}_write_peer'
        (g.out/'serial8-peer-source.py').write_bytes(Path(__file__).read_bytes())
        if continuation:
            self.record = g.data[key]
            if self.record['channel'] != channel or self.record['wire_bits'] != wire_bits:
                raise ValueError('continued channel-8 peer identity differs')
            return
        self.record = dict(source_sha256=sha(Path(__file__)), channel=channel, wire_bits=wire_bits,
            source_container_bytes=2,
            classification='explicit_write_only_clock_with_discarded_zero_rx',
            transfers=[], total_words=0, limit_words=16384, limit_batches=1024,
            peripheral_identity_known=False, protocol_accepted=False, bytes_are_pixels=False,
            cpu_register_redirection=False, ram_patches=[])
        self.record['dummy_rx_to_native_buffer']=allow_dummy_rx
        self.record['object_base']=hex(object_base)
        g.data[key] = self.record

    def clock_if_ready(self, sampled, *, resume=True):
        if not sampled['pio_active'] or not sampled['tx_queued'] or sampled['rx_queued'] >= 64:
            return False
        g = self.g
        g.qmp.command('stop')
        if 'Z8_UNKNOWN' in g.log():raise RuntimeError('strict device fault before peripheral clock')
        current = json.loads(g.qmp.command('qom-get', path='/machine', property='serial-state'))[self.channel]
        if not current['pio_active'] or not current['tx_queued'] or current['rx_queued'] >= 64:
            if resume:g.qmp.command('cont')
            return True
        if current['pio_word_bits'] != self.wire_bits:
            raise ValueError('PIO width differs from explicit peer contract')
        count = min(current['tx_queued'], 64-current['rx_queued'])
        batch = len(self.record['transfers'])
        if batch >= self.record['limit_batches'] or self.record['total_words']+count > self.record['limit_words']:
            raise RuntimeError('channel-8 write peer reached explicit bound')
        raw = save(g, f'serial{self.channel}-batch-{batch:03d}-descriptor', self.object_base+self.channel*0x68, 0x68)
        tx, rx = struct.unpack_from('<Q', raw, 0x20)[0], struct.unpack_from('<Q', raw, 0x30)[0]
        channel, total = struct.unpack_from('<I', raw, 8)[0], struct.unpack_from('<I', raw, 0x28)[0]
        if channel != self.channel or (rx and not self.allow_dummy_rx) or not tx or current['clocked']+count > total:
            raise ValueError('original request is not a bounded TX-only channel-8 buffer')
        # Native 40c146d8 loads halfwords regardless of the 8-bit wire width.
        source = save(g, f'serial{self.channel}-batch-{batch:03d}-tx', tx+2*current['clocked'], 2*count)
        expected = tuple(word & ((1<<self.wire_bits)-1) for word in struct.unpack('<'+'H'*count, source))
        g.qmp.command('qom-set', path='/machine', property='serial-clock', value=f'{self.channel}:'+'0000'*count)
        sent = bytes.fromhex(g.qmp.command('qom-get', path='/machine', property='serial-last-tx'))
        words = struct.unpack('<'+'H'*count, sent)
        row = dict(count=count, request_words=total, position=current['clocked'],
                   tx_pointer=hex(tx), rx_pointer=hex(rx), descriptor_hex=raw.hex(),
                   tx_container_hex=sent.hex(), source_container_hex=source.hex(),
                   expected_wire_hex=(bytes(expected) if self.wire_bits==8 else
                       struct.pack('<'+'H'*count,*expected)).hex(), tx_matches_original=expected == words)
        self.record['transfers'].append(row)
        self.record['total_words'] += count
        g.check(f'channel-{self.channel} clock transmits exact original words', row['tx_matches_original'])
        if resume:g.qmp.command('cont')
        return True
