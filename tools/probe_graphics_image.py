# SPDX-License-Identifier: GPL-2.0-or-later
from probe import sha

def ram_span(address, size, ram_mib=512):
    if ram_mib not in (512, 1024):
        raise ValueError('unsupported modeled RAM capacity')
    end = 0xa00000000 + ram_mib*1024*1024
    if not (0xa00000000 <= address < end and 0 <= size <= end - address):
        raise ValueError('capture outside modeled high RAM')

def save(g, label, address, size):
    ram_span(address, size, getattr(g, 'ram_mib', 512))
    raw = g.read_bytes(address, size) if size else b''
    path = g.out / (label + '.bin')
    path.write_bytes(raw)
    g.data.setdefault('captures', []).append(dict(label=label, address=hex(address), bytes=size,
                                                file=path.name, sha256=sha(path)))
    return raw
