# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Request-bound CCOMP peer inherited from the Z9 C5.32 functional experiment.

Only the observed family9/type2 command F3 (argument1) is acknowledged.
The original type3 decoder carries no result payload. This models the MCU
command lifecycle, not image processing, exposure hardware or DMA completion.
Other cameras must validate their own decoder before opting in.
"""
import hashlib
import struct

from mcu_frames import frames


def reply_for(wire):
    """Return an ACK only for the complete, checksummed observed request."""
    if len(wire) != 256 or sum(wire) & 255 != 255:
        return None
    if wire[:4] != bytes((9, 1, 240, 0)) or wire[252:254] != bytes((1, 1)):
        return None
    body = wire[8:248]
    if body != struct.pack('<3I', 2, 0xf3, 1) + bytes(228):
        return None
    body = bytes((3,)) + bytes(15)
    return body, frames(body, family=9)[0]


def queue_reply(peer, wire):
    reply = reply_for(wire)
    if reply is None:
        return False
    body, frame = reply
    peer.record.setdefault('ccomp_command_replies', []).append(dict(
        tx_index=peer.tx['row']['index'], selector='0xf3', argument=1,
        request_sha256=hashlib.sha256(wire).hexdigest(),
        reply_body_hex=body.hex(), reply_sha256=hashlib.sha256(frame).hexdigest(),
        classification='functional_mcu_command_ack',
        physical_mcu_verified=False))
    peer.pending.append((9, body, frame))
    return True
