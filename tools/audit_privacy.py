# SPDX-License-Identifier: GPL-2.0-or-later
"""Check tracked source and optional reachable history without printing secrets.

This catches common publication mistakes, not every possible private fact.
Review prose, permissions, provider metadata and artifacts separately.
"""
import argparse
from pathlib import Path, PurePosixPath
import re
import subprocess

PATTERNS = {
    'personal filesystem path': rb'/(?:Users|home|Volumes)/[A-Za-z0-9._~-]+|/(?:private/)?var/folders/|[A-Z]:\\Users\\',
    'private workspace reference': rb'nikon[-_]z[-_]research|nikon[_]firmware|codex[_]projects|[.]codex/(?:sessions|memories)',
    'private key': rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
    'credential token': rb'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{40,}',
    'credential-bearing URL': rb'''https?://[^\s/:@"']+:[^\s/@"']+@''',
    'literal credential assignment': rb'''(?i)\b(?:api[_-]?key|password|client[_-]?secret|access[_-]?token)\b['"]?\s*[:=]\s*['"][A-Za-z0-9/+_=-]{20,}['"]''',
}
COMPILED = {name: re.compile(pattern) for name, pattern in PATTERNS.items()}
PRIVATE_SUFFIXES = {'.bi', '.bin', '.raw', '.nef', '.dng', '.jpg', '.jpeg', '.png',
                    '.ppm', '.mov', '.mp4', '.pcap', '.pcapng', '.p12', '.pfx',
                    '.key', '.pem', '.zip', '.dmg', '.cdr', '.sqlite', '.db', '.log',
                    '.wav', '.s32le', '.s24le', '.so', '.dylib', '.dll', '.a', '.exe', '.lib'}
PRIVATE_PARTS = {'.local', '.aws', '.ssh', '.codex', '.env', '.git-credentials', 'AGENTS.md'}


def inspect(path, data, *, check_name=True):
    """Return category/line only; never include matching credential contents."""
    issues = []
    if check_name:
        name = PurePosixPath(path)
        if (name.suffix.lower() in PRIVATE_SUFFIXES or set(name.parts) & PRIVATE_PARTS
                or name.name.startswith('.env.')):
            issues.append(('private input/output filename', 0))
    if b'\0' in data:
        issues.append(('binary payload', 0))
    for category, pattern in COMPILED.items():
        for match in pattern.finditer(data):
            issues.append((category, data[:match.start()].count(b'\n') + 1))
    return issues


def audit(root, *, history=False):
    root = Path(root)
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
    failures = []
    for path in filter(None, paths):
        source = root/path
        if source.is_symlink():
            failures.append((path, 'tracked symlink', 0))
            continue
        for category, line in inspect(path, source.read_bytes()):
            failures.append((path, category, line))
    checked = sum(bool(x) for x in paths)
    objects = 0
    if history:
        # rev-list names a shared blob only once. Check every historical name
        # and mode too, including renamed payloads with identical contents.
        names_seen = set()
        for commit in subprocess.check_output(['git', 'rev-list', '--all'], cwd=root).splitlines():
            tree = subprocess.check_output(['git', 'ls-tree', '-rz', commit], cwd=root)
            for row in filter(None, tree.split(b'\0')):
                metadata, name = row.split(b'\t', 1)
                mode = metadata.split()[0]; path = name.decode(errors='replace')
                if (mode, path) in names_seen:
                    continue
                names_seen.add((mode, path))
                label = commit.decode()[:12]+':'+path
                if mode in (b'120000', b'160000'):
                    failures.append((label, 'historical symlink or submodule', 0))
                for category, line in inspect(path, b''):
                    failures.append((label, category, line))
        rows = subprocess.check_output(['git', 'rev-list', '--objects', '--all'], cwd=root).splitlines()
        with subprocess.Popen(['git', 'cat-file', '--batch'], cwd=root,
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE) as proc:
            for row in rows:
                oid, _, name = row.partition(b' ')
                proc.stdin.write(oid+b'\n'); proc.stdin.flush()
                header = proc.stdout.readline().split()
                if len(header) != 3:
                    raise RuntimeError('Could not inspect a reachable Git object')
                size = int(header[2]); data = proc.stdout.read(size)
                if len(data) != size or proc.stdout.read(1) != b'\n':
                    raise RuntimeError('Incomplete Git object')
                kind = header[1]
                if kind not in (b'blob', b'commit', b'tag'):
                    continue
                objects += 1
                path = name.decode(errors='replace')
                label = oid.decode()[:12] + (':'+path if path else '')
                for category, line in inspect(path, data, check_name=kind == b'blob'):
                    failures.append((label, category, line))
            proc.stdin.close()
            if proc.wait() != 0:
                raise RuntimeError('Git object inspection failed')
    return checked, objects, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true', help='Also inspect every reachable blob, commit and tag')
    args = parser.parse_args()
    checked, objects, failures = audit(Path(__file__).resolve().parents[1], history=args.history)
    for path, category, line in failures:
        print(f'{path}:{line}: {category}')
    print(f'Privacy patterns: {checked} tracked files, {objects} historical objects, {len(failures)} findings')
    raise SystemExit(bool(failures))


if __name__ == '__main__':
    main()
