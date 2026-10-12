# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Run original Z8 firmware with explicit synthetic inputs and native menus."""
from pathlib import Path
import signal
from runtime import arguments, verify
from full_guest import Guest
from boot_z8 import boot
from rom_inputs import attach
from stream import run
from control import Control, png_from_ppm

def main():
    p = arguments(__doc__)
    p.add_argument('--seconds', type=int, default=1800)
    p.add_argument('--port', type=int, default=8778)
    p.add_argument('--smoke', action='store_true')
    p.add_argument('--check-only', action='store_true')
    a = p.parse_args()
    if not 1 <= a.seconds <= 3600 or not 1024 <= a.port <= 65535: p.error('Invalid duration or port')
    firmware, manifest = verify(a.firmware)
    if not a.qemu.is_file() or not a.raw.is_file(): p.error('QEMU and synthetic RAW inputs must exist')
    if a.check_only:
        print('Z8 firmware and explicit runtime paths verified.'); return
    g = Guest(firmware, a.qemu, a.raw, a.output)
    g.command[g.command.index('-M')+1] = g.command[g.command.index('-M')+1].replace('nikon-z8-lab,', 'nikon-z8-full-lab,zr-sd-empty-fixture=on,')
    g.command += ['-device', f'loader,file={firmware},addr=0x40160000,force-raw=on,cpu-num=0']
    attach(g); g.data['command'] = g.command
    control = None if a.smoke else Control(a.port)
    if control: signal.signal(signal.SIGTERM, lambda *_: control.stop.set())
    try:
        with g:
            boot(g); run(g, 70 if a.smoke else a.seconds, control)
            g.check('no unmodeled MMIO in observed run', 'Z8_UNKNOWN' not in g.log())
            (g.out/'final.png').write_bytes(png_from_ppm(g.out/'final.ppm'))
    finally:
        if control: control.close()

if __name__ == '__main__': main()
