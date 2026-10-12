# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Verify the repository's source-only file inventory and fingerprints."""
from pathlib import Path
import hashlib
import json

def main():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root/'source-manifest.json').read_text())
    for name, digest in manifest['files'].items():
        path = root/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Source inventory mismatch: ' + name)
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p.name != '.DS_Store'
              and not any(x in ('.git', '.local', '__pycache__') for x in p.relative_to(root).parts)}
    if actual != set(manifest['files']) | {'source-manifest.json'}:
        raise ValueError('Unexpected source inventory additions or omissions')
    print('Verified', len(manifest['files']), 'source-only files')

if __name__ == '__main__':
    main()
