# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Original Z8 boot with a new virtual exFAT/NVMe card; no capture claim."""
from pathlib import Path
import sys,json,datetime,subprocess,struct,argparse
P=Path(__file__).resolve().parent
from runtime import arguments,verify
from full_guest import Guest
from boot_z8 import boot
from rom_inputs import attach
from capture_stream import run
from control import png_from_ppm
ap=arguments(__doc__,capture=True);ap.add_argument('--card-template',type=Path,required=True);ap.add_argument('--seconds',type=int,default=600);ap.add_argument('--settle',type=int,default=120);ap.add_argument('--experimental-preparation-profile',action='store_true',help='Hypothesis only: external bank8 offset999 input=1; not recovered factory data');ap.add_argument('--experimental-capture-selector5',action='store_true',help='Diagnostic ROM selector5 chooses placeholder record1; coefficients remain absent');ap.add_argument('--experimental-timed-single',action='store_true',help='Opt-in periodic DMA ownership experiment; needs timed build');ap.add_argument('--menu-actions',default='',help='Original MCU menu navigation, comma separated menu/ok/arrows');ap.add_argument('--manual-menu',action='store_true',help='Append actions to this run menu-control.json; capture=true releases shutter after queue');args=ap.parse_args();assert 30<=args.seconds<=1200 and 5<=args.settle<=300
firmware,_=verify(args.firmware);out=args.output.resolve()
g=Guest(firmware,args.qemu,args.raw,out)
g.capture_settle=args.settle
g.capture_menu_file=out/'menu-control.json' if args.manual_menu else None
if g.capture_menu_file:g.capture_menu_file.write_text(json.dumps({'actions':[],'capture':False})+'\n')
from z8_navigation_input import parse_actions,states
g.capture_menu_states=states(parse_actions(args.menu_actions)) if args.menu_actions else []
card=out/'capture-card.raw';source=args.card_template.resolve()
with source.open('rb') as f:
 m=f.read(512);assert m[510:]==b'\x55\xaa';start,sectors=struct.unpack_from('<II',m,454);f.seek(start*512);assert f.read(11)[3:11]==b'EXFAT   '
assert source.stat().st_size==8*1024**3
from copy_card import copy_card
copy_card(source,card)
g.command[g.command.index('-M')+1]=g.command[g.command.index('-M')+1].replace('nikon-z8-lab,','nikon-z8-full-lab,zr-sd-empty-fixture=on,')+',capture-gpio-model=on,pcie-link-diagnostic-mask=4,pcie-dbi-model=on,pcie-ram-dma-input=on,pcie-image-ram-dma-input=on,pcie-intx-model=on'
g.command+=['-device',f'loader,file={firmware},addr=0x40160000,force-raw=on,cpu-num=0','-drive',f'file={card},if=none,id=card,format=raw','-device','nvme,drive=card,serial=WL-Z8-CAPTURE,bus=dw-pcie,addr=0']
g.command[g.command.index('-M')+1]+=','+','.join(name+'=on' for name in json.loads((P/'capture-model-options.json').read_text()))
if args.experimental_timed_single:
 g.command[g.command.index('-M')+1]+=',z8-timed-single-model=on'
 g.data['experimental_timed_single']={'enabled':True,'physical_timing_verified':False,'completion_requires_real_dma':True}
attach(g)
# Supply the external bank-8 byte read during native preparation. This is
# a synthetic configuration hypothesis, not a firmware instruction patch.
if args.experimental_preparation_profile:
 p=out/'experimental-bank8-999.bin';p.write_bytes(b'\x01')
 g.command+=['-device',f'loader,file={p},addr=0x45a403e7,force-raw=on']
 g.data['experimental_preparation_profile']={'address':'0x45a403e7','value':1,'basis':'Original bank8 descriptor and offset999 branch; synthetic hypothesis, not recovered factory configuration','guest_code_modified':False}
# Select the observed processing record through an external ROM byte. The
# missing record coefficients are not recovered by this selector input.
if args.experimental_capture_selector5:
 p=out/'experimental-selector5.bin';p.write_bytes(b'\x01')
 g.command+=['-device',f'loader,file={p},addr=0x47f5af45,force-raw=on']
 g.data['experimental_capture_selector5']={'address':'0x47f5af45','value':1,'observed_selector':5,'record_body_recovered':False,'basis':'Z8 lookup41175e30 observed selector5/index0, then underflow41175e50; analogous upstream capture_processing_input.py','factory_calibration':False}
g.data['command']=g.command;g.data['virtual_card']={'path':str(card),'source':str(source),'partition_start':start,'sectors':sectors,'format':'host-created exFAT; guest files initially absent'}
for script in ['capture.py','capture_stream.py','gpio_bindings.py','capture_peer.py','ccomp_command_peer.py','capture-model-options.json','z8_navigation_input.py']:(out/script).write_bytes((P/script).read_bytes())
print(out,flush=True)
try:
 with g:
  try:
   boot(g)
   from gpio_bindings import capture
   rows=capture(g)
   for row,bit,irq in zip(rows[:2],(4,5),(59,60)):
    raw=bytes.fromhex(row['irq_hex'])
    assert (row['bank'],row['bit'],struct.unpack_from('<III',raw,4),struct.unpack_from('<Q',raw,0x18)[0])==(3,bit,(0,bit,irq),0x40fd9350),row
   run(g,args.seconds,None)
  finally:
   g.qmp.command('stop')
   g.data['card_model_state']={}
   for name in ['engine151-state','engine151-capture-pixels-state','engine151-raw-output-state','primary-d980-source-notify-state','pcie-dbi-state','capture-gpio-state','raw-pipeline-state','primary-d980-state','ccomp-gpio-state','engine150c-state','primary-d980-single-frame-state','primary-d980-prepared-start-state','primary-d980-source-notify-state','primary-d980-channel-boundary-state','primary-capture-direct-stop-state']:
    try:g.data['card_model_state'][name]=g.qmp.command('qom-get',path='/machine',property=name)
    except Exception as e:g.data['card_model_state'][name]={'error':str(e)}
   raw_side=g.data['card_model_state'].get('engine151-raw-output-state',{})
   if isinstance(raw_side,str):raw_side=json.loads(raw_side)
   if raw_side.get('jobs')==1 and not raw_side.get('pending') and raw_side.get('acks')==1:
    addr,size=raw_side['target'],raw_side['bytes']
    assert 0x840000000<=addr<0x900000000-size and 0<size<=128*1024**2
    dump=out/'engine151-raw-side-target.bin'
    reply=g.qmp.hmp(f'pmemsave {addr:#x} {size:#x} "{dump}"')
    assert dump.stat().st_size==size,reply
    g.data['raw_producer_snapshot']={'address':hex(addr),'bytes':size,'file':dump.name}
   g.qmp.command('screendump',filename=str(out/'final.ppm'))
   (out/'final.png').write_bytes(png_from_ppm(out/'final.ppm'))
finally:(out/'session-path.txt').write_text(str(out)+'\n')
