# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Run source, script-dependency, display and isolated hardware-contract checks."""
from pathlib import Path
import ast
import hashlib
import json
import os
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]

def main():
    for p in ROOT.rglob('*.py'):
        if '.local' not in p.parts:
            ast.parse(p.read_text(), filename=str(p))
    for name in ['tools/run.py', 'tools/capture.py', 'tools/build.py', 'tools/audit_nef.py', 'tools/make_card.py', 'qemu/prepare_source.py']:
        # Audit help needs the optional rawpy environment; its import is checked separately.
        if name == 'tools/audit_nef.py':
            continue
        subprocess.run([sys.executable, str(ROOT/name), '--help'], check=True, stdout=subprocess.DEVNULL)
    modules = {p.stem for p in (ROOT/'tools').glob('*.py')}
    allowed = sys.stdlib_module_names | {'numpy', 'PIL', 'rawpy'} | modules
    for p in (ROOT/'tools').glob('*.py'):
        for node in ast.walk(ast.parse(p.read_text())):
            names = ([x.name for x in node.names] if isinstance(node, ast.Import)
                     else [node.module] if isinstance(node, ast.ImportFrom) and node.module else [])
            assert all(n.split('.')[0] in allowed for n in names), (p.name, names)
    with tempfile.TemporaryDirectory(prefix='z8-tests-') as temp:
        for name in ['region', 'serial', 'timed']:
            exe = Path(temp)/name
            subprocess.run([os.environ.get('CC','cc'), '-Wall', '-Wextra', '-Werror', str(ROOT/f'tests/verify_{name}.c'), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)
        sys.path.insert(0, str(ROOT/'tools'))
        from copy_card import copy_card
        from rom_inputs import attach
        source, target = Path(temp)/'source.raw', Path(temp)/'target.raw'
        with source.open('wb') as f:
            f.write(b'header'); f.seek(1024*1024); f.write(b'tail')
        copy_card(source, target)
        assert source.read_bytes() == target.read_bytes()
        class Guest:
            pass
        g=Guest();g.out=Path(temp);g.command=[];g.data={}
        attach(g)
        assert len(g.data['synthetic_rom_inputs']['rows']) == 11
        assert all((g.out/x['file']).is_file() for x in g.data['synthetic_rom_inputs']['rows'])
    subprocess.run([sys.executable, str(ROOT/'tests/test_display_bank.py')], check=True)
    print('PASS source syntax, entry points, dependency closure, ROM fixtures, card copying, region/serial/timed contracts and actual display renderer')

if __name__ == '__main__':
    main()
