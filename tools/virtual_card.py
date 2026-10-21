# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit regular-file exFAT cards; attach by capability without copying media."""
from pathlib import Path
import json
import struct

def validate(path):
    path=Path(path).resolve()
    if not path.is_file() or ',' in str(path):
        raise ValueError('Card must be a regular file with no comma in its path')
    with path.open('rb') as source:
        header=source.read(512)
        if len(header)!=512 or header[510:]!=b'\x55\xaa':raise ValueError('Expected an MBR virtual card')
        start=struct.unpack_from('<I',header,454)[0]*512
        source.seek(start);boot=source.read(512)
        if len(boot)!=512 or boot[3:11]!=b'EXFAT   ':raise ValueError('Expected an exFAT partition')
    return path

def attach(guest,card,playback=False,native_mcu=False):
    properties={'capture-gpio-model':'on','pcie-link-diagnostic-mask':'4',
        'pcie-dbi-model':'on','pcie-ram-dma-input':'on',
        'pcie-image-ram-dma-input':'on','pcie-intx-model':'on'}
    if playback:
        names=json.loads(Path(__file__).with_name('capture-model-options.json').read_text())
        properties.update({name:'on' for name in names})
        properties['z8-jpeg-decode']='on'
    if native_mcu:properties['ccomp-gpio-model']='off'
    guest.command[guest.command.index('-M')+1]+=','+','.join(name+'='+value for name,value in properties.items())
    guest.command+=['-drive',f'file={card},if=none,id=card,format=raw',
        '-device','nvme,drive=card,serial=Z8-PERSISTENT,bus=dw-pcie,addr=0']
    guest.data['persistent_card']={'path':str(card),'guest_writable':True,'experimental_playback':playback}
