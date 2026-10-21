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
    p.add_argument('--experimental-preparation-profile', action='store_true', help='Synthetic bank8 offset999=1; missing factory preparation data remains unqualified')
    p.add_argument('--experimental-yuv-channels', action='store_true', help='Enable empty YUV channel readiness acknowledgement; no pixel completion')
    p.add_argument('--experimental-movie-selector16', action='store_true', help='Synthetic ROM selector16=index1; missing original coefficients remain unqualified')
    p.add_argument('--trace-transitions', action='store_true', help='Record bounded read-only native exception observations')
    p.add_argument('--replay', type=Path, help='Replay a JSON external-control sequence after native menu readiness')
    p.add_argument('--experimental-shared221', action='store_true', help='Use the experimental translated Z63 shared-device profile; Z8 HE/movie acceptance is unqualified')
    p.add_argument('--card', type=Path, help='Existing virtual exFAT card to attach persistently; guest writes update this file')
    p.add_argument('--experimental-playback', action='store_true', help='Enable the imported JPEG decoder/resize model; Z8 saved-photo guest acceptance remains unqualified')
    p.add_argument('--check-only', action='store_true')
    a = p.parse_args()
    if not 1 <= a.seconds <= 3600 or not 1024 <= a.port <= 65535: p.error('Invalid duration or port')
    firmware, manifest = verify(a.firmware)
    if not a.qemu.is_file() or not a.raw.is_file(): p.error('QEMU and synthetic RAW inputs must exist')
    if a.card:
        a.card=a.card.resolve()
        if not a.card.is_file() or ',' in str(a.card): p.error('Card must be a regular file with no comma in its path')
        with a.card.open('rb') as f:
            header=f.read(512)
            if len(header)!=512 or header[510:]!=b'\x55\xaa': p.error('Expected an MBR virtual card')
            import struct
            start=struct.unpack_from('<I',header,454)[0]*512
            f.seek(start);card_boot=f.read(512)
            if len(card_boot)!=512 or card_boot[3:11]!=b'EXFAT   ': p.error('Expected an exFAT partition')
    if a.experimental_playback and not a.card: p.error('--experimental-playback requires --card')
    if a.check_only:
        print('Z8 firmware and explicit runtime paths verified.'); return
    if a.replay and a.smoke: p.error('--replay and --smoke are mutually exclusive')
    from replay import Replay
    replay = Replay(a.replay) if a.replay else None
    g = Guest(firmware, a.qemu, a.raw, a.output)
    if replay: g.data['input_replay'] = replay.actions
    g.trace_transitions = a.trace_transitions
    g.command[g.command.index('-M')+1] = g.command[g.command.index('-M')+1].replace('nikon-z8-lab,', 'nikon-z8-full-lab,zr-sd-empty-fixture=on,')
    g.command += ['-device', f'loader,file={firmware},addr=0x40160000,force-raw=on,cpu-num=0']
    if a.experimental_shared221:
        import json
        profile=json.loads(Path(__file__).with_name('experimental-shared221-profile.json').read_text())
        g.command[g.command.index('-M')+1]+=','+','.join(k+'='+v for k,v in profile['properties'].items())
        g.data['experimental_shared221']=profile
    if a.experimental_yuv_channels:
        g.command[g.command.index('-M')+1]+=',yuvcmp-config-model=on,yuvcmp-channels-model=on,yuvcmp-channel-ready-model=on'
    if a.card:
        extra='capture-gpio-model=on,pcie-link-diagnostic-mask=4,pcie-dbi-model=on,pcie-ram-dma-input=on,pcie-image-ram-dma-input=on,pcie-intx-model=on'
        if a.experimental_playback:
            import json
            extra+=','+','.join(name+'=on' for name in json.loads((Path(__file__).with_name('capture-model-options.json')).read_text()))
            extra+=',z8-jpeg-decode=on'
        g.command[g.command.index('-M')+1]+=','+extra
        g.command+=['-drive',f'file={a.card},if=none,id=card,format=raw',
                    '-device','nvme,drive=card,serial=Z8-PERSISTENT,bus=dw-pcie,addr=0']
        g.data['persistent_card']={'path':str(a.card),'guest_writable':True,'experimental_playback':a.experimental_playback}
    attach(g)
    if a.experimental_preparation_profile:
        preparation=g.out/'experimental-bank8-999.bin';preparation.write_bytes(b'\x01')
        g.command+=['-device',f'loader,file={preparation},addr=0x45a403e7,force-raw=on']
        g.data['experimental_preparation_profile']={'address':'0x45a403e7','value':1,'factory_calibration':False}
    if a.experimental_movie_selector16:
        selector=g.out/'experimental-selector16.bin';selector.write_bytes(b'\x01')
        g.command+=['-device',f'loader,file={selector},addr=0x47f5af50,force-raw=on']
        g.data['experimental_movie_selector16']={'address':'0x47f5af50','value':1,'factory_calibration':False,'basis':'native selector16 underflows absent table record at 41170d84'}
    g.data['command'] = g.command
    control = replay or (None if a.smoke else Control(a.port))
    if control: signal.signal(signal.SIGTERM, lambda *_: control.stop.set())
    try:
        with g:
            boot(g); run(g, 70 if a.smoke else a.seconds, control)
            if replay: g.data['replay_status']=replay.status()
            g.check('no unmodeled MMIO in observed run', 'Z8_UNKNOWN' not in g.log())
            (g.out/'final.png').write_bytes(png_from_ppm(g.out/'final.ppm'))
    finally:
        if control: control.close()

if __name__ == '__main__': main()
