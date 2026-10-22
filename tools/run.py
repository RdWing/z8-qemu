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
import movie_inputs
import virtual_card
import trace_plugin

def main():
    p = arguments(__doc__)
    p.add_argument('--seconds', type=int, default=1800)
    p.add_argument('--port', type=int, default=8778)
    p.add_argument('--smoke', action='store_true')
    p.add_argument('--experimental-independent-pixel-clock', action='store_true', help='Use the baseline periodic pixel clock instead of donor capture-tick pacing; requires shared profile')
    p.add_argument('--experimental-preparation-profile', action='store_true', help='Synthetic bank8 offset999=1; missing factory preparation data remains unqualified')
    p.add_argument('--trace-transitions', action='store_true', help='Record bounded read-only native exception observations')
    p.add_argument('--replay', type=Path, help='Replay a JSON external-control sequence after native menu readiness')
    p.add_argument('--experimental-shared221', action='store_true', help='Use the experimental translated Z63 shared-device profile; bounded HE/movie acceptance is documented separately')
    p.add_argument('--card', type=Path, help='Existing virtual exFAT card to attach persistently; guest writes update this file')
    p.add_argument('--experimental-playback', action='store_true', help='Enable the imported JPEG decoder/resize model; saved-preview display accepted; recovery/zoom remain open')
    p.add_argument('--check-only', action='store_true')
    movie_inputs.arguments(p)
    trace_plugin.arguments(p)
    a = p.parse_args()
    try:trace_profile=trace_plugin.validate(a)
    except ValueError as error:p.error(str(error))
    try:movie_inputs.validate(a)
    except ValueError as error:p.error(str(error))
    if not 1 <= a.seconds <= 3600 or not (a.port == 0 or 1024 <= a.port <= 65535): p.error('Invalid duration or port')
    if a.experimental_independent_pixel_clock and not a.experimental_shared221: p.error('--experimental-independent-pixel-clock requires --experimental-shared221')
    firmware, manifest = verify(a.firmware)
    if not a.qemu.is_file() or not a.raw.is_file(): p.error('QEMU and synthetic RAW inputs must exist')
    if a.card:
        try:a.card=virtual_card.validate(a.card)
        except ValueError as error:p.error(str(error))
    if a.experimental_playback and not a.card: p.error('--experimental-playback requires --card')
    if a.check_only:
        print('Z8 firmware and explicit runtime paths verified.'); return
    if a.replay and a.smoke: p.error('--replay and --smoke are mutually exclusive')
    from replay import Replay
    replay = Replay(a.replay) if a.replay else None
    g = Guest(firmware, a.qemu, a.raw, a.output)
    trace_plugin.attach(g,trace_profile)
    if replay: g.data['input_replay'] = replay.actions
    g.trace_transitions = a.trace_transitions
    g.extra_boundary_inputs = a.experimental_boundary_inputs
    g.command[g.command.index('-M')+1] = g.command[g.command.index('-M')+1].replace('nikon-z8-lab,', 'nikon-z8-full-lab,zr-sd-empty-fixture=on,')
    g.command += ['-device', f'loader,file={firmware},addr=0x40160000,force-raw=on,cpu-num=0']
    if a.experimental_shared221:
        import json
        profile=json.loads(Path(__file__).with_name('experimental-shared221-profile.json').read_text())
        g.command[g.command.index('-M')+1]+=','+','.join(k+'='+v for k,v in profile['properties'].items())
        g.data['experimental_shared221']=profile
    if a.experimental_independent_pixel_clock:
        g.command[g.command.index('-M')+1]+=',z8-liveview-frame-done=off'
        g.data['experimental_independent_pixel_clock']=True
    if a.card:virtual_card.attach(g,a.card,playback=a.experimental_playback)
    attach(g)
    if a.experimental_preparation_profile:
        preparation=g.out/'experimental-bank8-999.bin';preparation.write_bytes(b'\x01')
        g.command+=['-device',f'loader,file={preparation},addr=0x45a403e7,force-raw=on']
        g.data['experimental_preparation_profile']={'address':'0x45a403e7','value':1,'factory_calibration':False}
    movie_inputs.attach(g,a)
    g.data['command'] = g.command
    control = replay or (None if a.smoke else Control(a.port,playback=a.experimental_playback))
    if control and not replay:
        control.write_endpoint(g.out)
    if control:
        g.startup_cancelled=control.stop.is_set
        signal.signal(signal.SIGTERM, lambda *_: control.stop.set())
    try:
        with g:
            boot(g); run(g, 70 if a.smoke else a.seconds, control)
            if replay: g.data['replay_status']=replay.status()
            g.check('no unmodeled MMIO in observed run', 'Z8_UNKNOWN' not in g.log())
            (g.out/'final.png').write_bytes(png_from_ppm(g.out/'final.ppm'))
    finally:
        if control: control.close()

if __name__ == '__main__': main()
