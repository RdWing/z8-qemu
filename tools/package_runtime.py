# SPDX-License-Identifier: GPL-2.0-or-later
"""Copy only fingerprinted source-manifest tools into a new desktop runtime."""
import hashlib
import json
from pathlib import Path, PurePosixPath
from audit_privacy import inspect


def copy_runtime(root, destination):
    root = Path(root).resolve(); destination = Path(destination)
    manifest = json.loads((root/'source-manifest.json').read_text())
    prepared = []
    for name, expected in manifest['files'].items():
        if not name.startswith('tools/'):
            continue
        path = PurePosixPath(name)
        if (len(path.parts) < 2 or '..' in path.parts or '\\' in name
                or path.as_posix() != name or path.suffix not in {'.py', '.json', '.html', '.cpp'}):
            raise ValueError('Unexpected runtime source path')
        source = root/name
        current = source
        while current != root:
            if current.is_symlink():
                raise ValueError('Runtime source may not be a symlink')
            current = current.parent
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError('Runtime source fingerprint mismatch: '+name)
        if inspect(name, data):
            raise ValueError('Runtime source failed privacy patterns: '+name)
        prepared.append((Path(*path.parts[1:]), data))
    if not prepared:
        raise ValueError('Source manifest contains no runtime tools')
    destination.mkdir(parents=True, exist_ok=False)
    for relative, data in prepared:
        target = destination/relative; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return len(prepared)
