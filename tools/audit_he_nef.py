#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing: Z8 adaptation.
"""Audit a guest-written HE NEF and extract its actual RAW strip, read-only.

Requires ExifTool. Optionally invoke decode_he to decode all RAW samples.
This does not repair a container or prove original Nikon encoder arithmetic.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def audit(path, output, decoder=None, previews=False):
    if not 8 <= path.stat().st_size <= 128 * 1024 * 1024:
        raise ValueError('NEF file size outside supported range')
    meta = json.loads(subprocess.check_output([
        'exiftool', '-j', '-G1', '-s', '-a', '-n', '-ImageWidth', '-ImageHeight',
        '-Compression', '-StripOffsets', '-StripByteCounts', '-NEFCompression', str(path)
    ]))[0]
    if meta.get('Nikon:NEFCompression') not in (13, 14):
        raise ValueError('Not a native HE/HE-star NEF compression label')
    candidates = []
    for key, value in meta.items():
        if key.endswith(':Compression') and value == 34713:
            group = key.rsplit(':', 1)[0]
            width, height = meta.get(group+':ImageWidth', 0), meta.get(group+':ImageHeight', 0)
            if width and height:
                candidates.append((group, width, height))
    if len(candidates) != 1:
        raise ValueError('Expected one nonempty compressed RAW image IFD')
    group, width, height = candidates[0]
    offset, amount = meta.get(group+':StripOffsets'), meta.get(group+':StripByteCounts')
    if not isinstance(offset, int) or not isinstance(amount, int) or offset < 8 or amount < 256:
        raise ValueError('Missing RAW strip location/byte count')
    if amount > 32*1024*1024 or offset > path.stat().st_size-amount:
        raise ValueError('RAW strip exceeds file or codec bounds')
    with path.open('rb') as source:
        source.seek(offset)
        packet = source.read(amount)
    if packet[:2] != b'\xff\x10' or packet[-2:] != b'\xff\x11':
        raise ValueError('RAW strip lacks HE start/end markers')
    output.mkdir(parents=True, exist_ok=False)
    strip = output/'raw.he'
    strip.write_bytes(packet)
    report = dict(file_bytes=path.stat().st_size, file_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  nef_compression=meta['Nikon:NEFCompression'], width=width, height=height,
                  raw_offset=offset, raw_bytes=amount, raw_sha256=hashlib.sha256(packet).hexdigest(),
                  full_raw_decode=False, physical_codec_equivalence=False)
    if decoder:
        decoded = output/'bayer.u16'
        result = subprocess.run([str(decoder.resolve()), str(strip), str(decoded)], check=True,
                                capture_output=True, text=True)
        geometry = json.loads(result.stdout.splitlines()[0])
        if geometry.get('width') != width or geometry.get('height') != height:
            raise ValueError('Codestream dimensions do not match TIFF geometry')
        if decoded.stat().st_size != width*height*2:
            raise ValueError('Decoded Bayer sample count does not match TIFF geometry')
        report.update(full_raw_decode=True, decoder_log=result.stdout.splitlines(),
                      decoded_sha256=hashlib.sha256(decoded.read_bytes()).hexdigest())
    if previews:
        from PIL import Image
        import io
        report['previews']=[]
        for tag in ['ThumbnailImage','PreviewImage','JpgFromRaw']:
            data=subprocess.check_output(['exiftool','-b','-'+tag,str(path)])
            if not data: raise ValueError('Missing '+tag)
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                report['previews'].append(dict(tag=tag,width=image.width,height=image.height,
                    bytes=len(data),sha256=hashlib.sha256(data).hexdigest()))
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('nef', type=Path)
    parser.add_argument('--output', type=Path, required=True, help='new evidence directory')
    parser.add_argument('--decoder', type=Path, help='compiled tools/decode_he.cpp')
    parser.add_argument('--previews', action='store_true', help='Decode all three embedded JPEGs with Pillow')
    args = parser.parse_args()
    print(json.dumps(audit(args.nef, args.output, args.decoder, args.previews), indent=2))


if __name__ == '__main__':
    main()
