# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Explicit local runtime paths; no Nikon inputs are distributed."""
from pathlib import Path
import argparse, hashlib, json
ROOT = Path(__file__).resolve().parents[1]
MAIN_SHA = "2b43a31c9de838f84b12416de4348a7004e65be07f853ec56ec2b10f3a8e3853"

def arguments(description, capture=False):
    p = argparse.ArgumentParser(description=description)
    p.add_argument('--firmware', type=Path, required=True)
    p.add_argument('--qemu', type=Path, required=True)
    p.add_argument('--raw', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True, help='Fresh run directory')
    return p

def verify(firmware):
    firmware = firmware.resolve()
    if firmware.stat().st_size != 81807709 or hashlib.file_digest(firmware.open('rb'), 'sha256').hexdigest() != MAIN_SHA:
        raise ValueError('Expected original Z8 C3.11 MAIN payload (CRC trailer excluded)')
    return firmware, json.loads((ROOT/'source-manifest.json').read_text())
