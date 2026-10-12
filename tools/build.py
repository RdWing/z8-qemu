# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Build the Z8 overlay using a user-provided QEMU 11.1.1 source tree."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu-source', type=Path, required=True)
    parser.add_argument('--build-dir', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.jobs <= 64:
        parser.error('Use 1..64 build jobs')
    root = Path(__file__).resolve().parents[1]
    source, build = args.qemu_source.resolve(), args.build_dir.resolve()
    module = importlib.util.spec_from_file_location('z8_prepare', root/'qemu/prepare_source.py')
    prepare = importlib.util.module_from_spec(module)
    module.loader.exec_module(prepare)
    receipt = prepare.prepare(source)
    build.mkdir(parents=True, exist_ok=True)
    if not (build/'build.ninja').exists():
        configure = [str(source/'configure'), '--target-list=aarch64-softmmu', '--disable-docs', '--disable-werror']
        if sys.platform == 'darwin':
            # The camera uses its own scanout; Apple's unrelated PVG device
            # uses APIs removed from recent SDKs.
            configure.append('--disable-pvg')
        subprocess.run(configure, cwd=build, check=True)
    subprocess.run(['ninja', '-C', str(build), '-j', str(args.jobs), 'qemu-system-aarch64'], check=True)
    binary = build/'qemu-system-aarch64'
    manifest = {'qemu_version': '11.1.1', 'overlay': receipt,
                'binary_sha256': hashlib.file_digest(binary.open('rb'), 'sha256').hexdigest(),
                'qualification': 'Build receipt only; run the Z8 boot/capture acceptance separately.'}
    (build/'z8-build-receipt.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(binary)

if __name__ == '__main__':
    main()
