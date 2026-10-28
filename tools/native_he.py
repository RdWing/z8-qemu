# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Explicit synthetic HE preparation for original MAIN/EX contact replays."""
import json
from movie_inputs import native_modes_enabled

OPTIONS=('experimental_he_still','experimental_preparation_profile',
         'experimental_capture_selector5','experimental_timed_single')
STATES=('engine152c-he-still-state','engine152c-request-state','primary-d980-state',
        'primary-d980-single-frame-state','primary-d980-source-notify-state',
        'serial5-tx-drain-state','raw-pipeline-source-boundary-state',
        'backend-program-epoch-state')


def arguments(parser):
    for name in OPTIONS:
        parser.add_argument('--'+name.replace('_','-'),action='store_true',
                            help='Explicit native HE synthetic profile; all four options, a card and original-EX contacts are required')

    parser.add_argument('--experimental-he-live-preview',action='store_true',
                        help='Ordinary HE live-preview profile: preparation byte zero and guarded finite input/source/program epochs; requires all native HE options')

def validate(args):
    chosen=[getattr(args,name,False) for name in OPTIONS]
    if getattr(args,'experimental_he_live_preview',False) and not all(chosen):
        raise ValueError('HE live preview requires the complete native HE profile')
    if any(chosen) and not (all(chosen) and args.card and (args.contact_replay or getattr(args,'native_controls',False)) and native_modes_enabled(args)):
        raise ValueError('Native HE requires all four HE/preparation/selector/timed-single options, complete experimental Movie profile, card and original-EX contacts')
    return all(chosen)


def attach(guest,args):
    if not validate(args):return
    index=guest.command.index('-M')+1
    guest.command[index]+=',z8-timed-single-model=on,engine152c-stream-receiver-model=on,engine152c-he-still-model=on,engine153-alternate-bank-model=on,mcu-capture-sync-wires=on,serial5-tx-drain-model=on'
    live=getattr(args,'experimental_he_live_preview',False)
    if live:
        guest.command[index]+=',primary-d980-live-single-model=on,raw-pipeline-input-pair-model=on,backend-program-epoch-model=on'
    for name,address in [('experimental-bank8-999.bin',0x45a403e7),('experimental-selector5.bin',0x47f5af45)]:
        path=guest.out/name;path.write_bytes(bytes([0 if live and address==0x45a403e7 else 1]))
        guest.command+=['-device',f'loader,file={path},addr={address:#x},force-raw=on']
    guest.data['experimental_native_he']={
        'host_mcu_messages':False,'guest_code_modified':False,
        'preparation_profile':{'address':'0x45a403e7','value':0 if live else 1},
        'live_preview_profile':live,
        'capture_selector5':{'address':'0x47f5af45','value':1},
        'factory_calibration':False,'physical_codec_verified':False,'capture_sync_wires':True,
        'audio_tx_sink':{'completion_requires_source_bytes':True,'dac_output':False,'physical_timing_verified':False},
        'input_scope':'Declared original EX and separate MAIN GPIO contacts; physical shared wiring unqualified'}




def control_modes_enabled(args):
    """HE preparation and Movie preview have separate workflow qualification."""
    return native_modes_enabled(args) and not any(getattr(args,name,False) for name in OPTIONS)


def capture_ready(guest,row):
    """C3.11 shooting mode is 6; menu/review modes cannot admit a new shot."""
    he=guest.data['native_he_models']['engine152c-he-still-state']
    mode=int.from_bytes(bytes.fromhex(row['ui_control_hex'])[4:8],'little')
    return (not row['preparing_capture'] and mode==6 and
            guest.read_bytes(0xa03bd042c,1)==b'\x01' and he['jobs']<16 and
            not he['pending'] and not he['stop_pending'])


def sample(guest):
    if not guest.data.get('experimental_native_he'):return
    states={name:json.loads(guest.qmp.command('qom-get',path='/machine',property=name)) for name in STATES}
    guest.data['native_he_models']=states
    he=states['engine152c-he-still-state']
    index=he['jobs']
    if not index or he['acks']!=index or he['pending']:return
    captures=guest.data.setdefault('he_capture_snapshots',[])
    if any(row['capture_index']==index for row in captures):return
    if index!=len(captures)+1 or index>16:
        raise ValueError('Native HE snapshots require consecutive captures within the 16-frame bound')
    suffix='' if index==1 else f'-{index:03d}'
    receiver=states['engine152c-request-state'];sensor=states['primary-d980-state']
    pitch=sensor['submitted']['0x100'];height=receiver['height']
    snapshots=[(f'he-receiver-output{suffix}.bin',receiver['output'],receiver['capacity']),
               (f'he-sensor-packed14{suffix}.bin',sensor['last_physical'],pitch*height)]
    for _,address,size in snapshots:
        if not (0<size<=128*1024**2 and 0x800000000<=address<0x900000000-size):
            raise ValueError('HE snapshot must lie entirely within the modeled image RAM')
    running=guest.qmp.command('query-status')['running']
    if running:guest.qmp.command('stop')
    try:
        for name,address,size in snapshots:
            guest.qmp.command('pmemsave',val=address,size=size,filename=str(guest.out/name))
    finally:
        if running:guest.qmp.command('cont')
    record={'capture_index':index,'output':snapshots[0][0],'input':snapshots[1][0],
            'width':receiver['width'],'height':height,'pitch':pitch}
    captures.append(record)
    if index==1:guest.data['he_snapshots']=record
