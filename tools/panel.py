# SPDX-License-Identifier: GPL-2.0-or-later
"""Decode the bounded functional EX panel memory without assuming body rotation."""
import struct
import zlib

WIDTH,HEIGHT=144,168
BYTES=WIDTH*HEIGHT//8


def png(bits, display_on):
    if not isinstance(bits,str) or len(bits)!=BYTES*2 or type(display_on) is not bool:
        raise ValueError('Expected 3024 panel bytes and an explicit display state')
    try:data=bytes.fromhex(bits)
    except ValueError:raise ValueError('Expected hexadecimal panel memory') from None
    if len(data)!=BYTES:raise ValueError('Expected exactly 3024 panel bytes')
    # Exact model line/shift order: line 1 first, bit 7 at the left.
    # DISP low blanks the view; retained memory is not presented as lit pixels.
    scan=bytearray()
    for y in range(HEIGHT):
        scan.append(0)
        for x in range(WIDTH):
            scan.append(255 if not display_on or data[y*(WIDTH//8)+x//8]&(0x80>>(x%8)) else 0)
    def chunk(tag,value):return struct.pack('>I',len(value))+tag+value+struct.pack('>I',zlib.crc32(tag+value)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',WIDTH,HEIGHT,8,0,0,0,0))+chunk(b'IDAT',zlib.compress(scan,3))+chunk(b'IEND',b'')
