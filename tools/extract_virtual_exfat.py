# SPDX-License-Identifier: GPL-2.0-or-later
"""Extract one actual file from an already audited, stopped virtual card.

This only reads the volume. It never constructs a camera file or changes a
card. The existing directory parser validates entry checksums and geometry.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import struct
from inspect_virtual_exfat import catalog
from virtual_exfat_window import window


def extract(volume, name, output, *, max_bytes=256*1024*1024):
    volume, output = Path(volume), Path(output)
    origin,volume_bytes=window(volume)
    rows = [x for x in catalog(volume)['files'] if x['path'] == name and not x['directory']]
    if len(rows) != 1:
        raise ValueError('One exact, validated file entry required')
    row = rows[0]
    length = row['bytes']
    if (not isinstance(max_bytes,int) or max_bytes<=0 or
            not 0 < length <= min(max_bytes,volume.stat().st_size) or row['valid_bytes'] != length):
        raise ValueError('Bounded, fully initialized file required')
    if output.exists() or not output.parent.is_dir():
        raise ValueError('Fresh output in an existing private directory required')
    digest = hashlib.sha256()
    with volume.open('rb') as src, output.open('xb') as dst:
        src.seek(origin)
        boot = src.read(512)
        sector = 1 << boot[108]
        cluster = sector << boot[109]
        fat, _, heap, count, _ = struct.unpack_from('<IIIII', boot, 80)
        current = row['first_cluster']
        seen = set()
        left = length
        for _ in range(math.ceil(length/cluster)):
            if not 2 <= current < count+2 or current in seen:
                raise ValueError('Invalid, short or cyclic actual file chain')
            seen.add(current)
            offset = heap*sector+(current-2)*cluster
            size = min(left, cluster)
            if offset+size > volume_bytes:
                raise ValueError('Actual file span exceeds the volume')
            src.seek(origin+offset)
            data = src.read(size)
            if len(data) != size:
                raise ValueError('Short actual file read')
            dst.write(data)
            digest.update(data)
            left -= size
            if left:
                if row['contiguous']:
                    current += 1
                else:
                    src.seek(origin+fat*sector+current*4)
                    value = src.read(4)
                    if len(value) != 4:
                        raise ValueError('Short FAT read')
                    current = struct.unpack('<I', value)[0]
        if left:
            raise ValueError('Actual file incomplete')
    result = dict(volume=str(volume), entry=row, output=str(output), bytes=length,
                  sha256=digest.hexdigest(), camera_image_decoded=False,
                  scope='actual initialized file bytes extracted read-only; no substituted data, codec or camera-file acceptance')
    output.with_suffix(output.suffix+'.extraction.json').open('x').write(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--volume', type=Path, required=True)
    p.add_argument('--file', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(extract(a.volume, a.file, a.output)))
