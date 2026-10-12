# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Synthetic MCU frames inherited from the Z9 C5.32 native RX contract.

These are diagnostic inputs, not captured physical MCU traffic. Unidentified
header/footer fields are zero. Routing/body semantics are model-specific.
"""
import struct


def status_body(changes=None):
    body = bytearray(128)
    body[0] = 3
    for offset, value in (changes or {}).items():
        if not 1 <= offset < len(body) or not 0 <= value <= 255:
            raise ValueError("invalid status byte")
        body[offset] = value
    return bytes(body)


def frames(body, family=1, channel=1):
    capacities = {1: 240, 2: 240, 3: 1500}
    if not 1 <= family <= 18 or channel not in capacities:
        raise ValueError("unsupported family/channel")
    if not 0 < len(body) <= capacities[channel]:
        raise ValueError("body exceeds the observed channel buffer capacity")
    count = (len(body) + 239) // 240
    result = []
    for index in range(count):
        packet = bytearray(256)
        packet[0], packet[1] = family, channel
        struct.pack_into("<H", packet, 2, len(body))
        fragment = body[index * 240:(index + 1) * 240]
        packet[8:8 + len(fragment)] = fragment
        packet[0xFC], packet[0xFD] = count, index + 1
        packet[0xFF] = (~sum(packet[:0xFF])) & 255
        result.append(bytes(packet))
    return result


def status_frame():
    return frames(status_body({4: 1, 5: 1, 0xC: 1}))[0]
