# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicit functional Movie inputs shared by the host and original EX launchers."""
def arguments(parser):
    parser.add_argument('--experimental-boundary-inputs', action='store_true', help='Supply declared auxiliary1/global0 diagnostic boundaries; requires shared profile')
    parser.add_argument('--experimental-sensor-source-clock', action='store_true', help='Continue configured source consumers from existing Z8 sensor VD; requires shared profile')
    parser.add_argument('--experimental-yuv-channels', action='store_true', help='Acknowledge empty YUV arm as ready, without DMA or completion')
    parser.add_argument('--experimental-movie-selector16', action='store_true', help='Synthetic external ROM selector16=index1; not factory coefficients')

def validate(args):
    for name in ('experimental_sensor_source_clock','experimental_boundary_inputs'):
        if getattr(args,name,False) and not args.experimental_shared221:
            raise ValueError('--'+name.replace('_','-')+' requires --experimental-shared221')

def attach(guest,args):
    index=guest.command.index('-M')+1
    if args.experimental_sensor_source_clock:
        guest.command[index]+=',z8-sensor-source-clock=on'
        guest.data['experimental_sensor_source_clock']=True
    if args.experimental_yuv_channels:
        guest.command[index]+=',yuvcmp-config-model=on,yuvcmp-channels-model=on,yuvcmp-channel-ready-model=on'
    if args.experimental_movie_selector16:
        selector=guest.out/'experimental-selector16.bin';selector.write_bytes(b'\x01')
        guest.command+=['-device',f'loader,file={selector},addr=0x47f5af50,force-raw=on']
        guest.data['experimental_movie_selector16']={'address':'0x47f5af50','value':1,'factory_calibration':False,'basis':'native selector16 underflows absent table record at 41170d84'}

def native_modes_enabled(args):
    return all(getattr(args,name,False) for name in ('experimental_shared221',
        'experimental_boundary_inputs','experimental_sensor_source_clock',
        'experimental_yuv_channels','experimental_movie_selector16'))
