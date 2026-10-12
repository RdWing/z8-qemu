# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
import struct

def require_lossless14(tags, linearization):
    """Reject the packed-pixel payload that LibRaw accepts by size alone.

    C3.11's F0 metadata declares Nikon lossless entropy coding with four
    2048 predictors. A packed Bayer transport buffer is not that bitstream.
    This checks the profile before the independent decoder checks pixels.
    """
    if [tags.get(k) for k in (256, 257, 258, 259)] != [[8280], [5520], [14], [34713]]:
        raise ValueError('Expected Z8 8280x5520 14-bit Nikon-compressed RAW IFD')
    if not linearization.startswith(b'F0' + struct.pack('<4H', *([2048] * 4))):
        raise ValueError('Expected F0 lossless metadata with four 2048 predictors')
    sizes = tags.get(279, [])
    packed_sizes = [((8280 * 7 * channels // 4 + 15) // 16 * 16) * 5520
                    for channels in (1, 3)]
    if len(sizes) != 1 or sizes[0] <= 4:
        raise ValueError('Expected one complete Nikon lossless RAW strip')
    if sizes[0] in packed_sizes:
        raise ValueError('RAW strip matches LibRaw packed-size fallback; Nikon lossless encoding is unverified')

def image_ifds(data):
    if data[:4] != b'II*\0':
        raise ValueError('Expected actual little-endian TIFF NEF')
    seen, rows = set(), []

    def visit(offset):
        if not offset or offset in seen:
            return
        if len(seen) >= 32 or not 0 <= offset <= len(data)-2:
            raise ValueError('Native IFD bound reached')
        seen.add(offset)
        n = struct.unpack_from('<H', data, offset)[0]
        if n > 1024 or offset+2+12*n+4 > len(data):
            raise ValueError('Native IFD truncated')
        tags = {}
        for i in range(n):
            at = offset+2+12*i
            tag, kind, count, pointer = struct.unpack_from('<HHII', data, at)
            if tag not in (254,256,257,258,259,262,273,278,279,330,513,514) or kind not in (3,4):
                continue
            unit, fmt = (2,'H') if kind == 3 else (4,'I')
            if not 0 < count <= 1024:
                raise ValueError('Native image tag count invalid')
            start = at+8 if unit*count <= 4 else pointer
            if start+unit*count > len(data):
                raise ValueError('Native image tag payload outside file')
            tags[tag] = list(struct.unpack_from('<'+fmt*count, data, start))
        rows.append(dict(offset=offset, tags=tags))
        for child in tags.get(330, []):
            visit(child)
        visit(struct.unpack_from('<I', data, offset+2+12*n)[0])

    visit(struct.unpack_from('<I', data, 4)[0])
    return rows
