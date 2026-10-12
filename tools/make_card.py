# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Create a fresh 8 GiB MBR/exFAT virtual card using host exFAT tools."""
import argparse,json
from pathlib import Path
from virtual_recording_card import create
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True)
print(json.dumps(create(a.output,'exfat'),indent=2))
