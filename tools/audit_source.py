# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Verify the repository's source-only file inventory and fingerprints."""
from pathlib import Path
import hashlib
import json
import os

def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root/'source-manifest.json').read_text())
    for name, digest in manifest['files'].items():
        path = root/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Source inventory mismatch: ' + name)
    excluded = {'.git', '.local', '__pycache__'}
    actual = set()
    for base, directories, files in os.walk(root, followlinks=False):
        directories[:] = [name for name in directories if name not in excluded]
        for name in files:
            path = Path(base)/name
            if name not in excluded and name != '.DS_Store' and path.is_file():
                actual.add(str(path.relative_to(root)))
    if actual != set(manifest['files']) | {'source-manifest.json'}:
        raise ValueError('Unexpected source inventory additions or omissions')
    print('Verified', len(manifest['files']), 'source-only files')

if __name__ == '__main__':
    main()
