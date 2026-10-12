# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Generate synthetic external-ROM inputs for the Z8 model.
These are not factory calibration or recovered parameter tables.
"""
import hashlib,json,struct

def attach(g):
 fields={0x47f62dd4:b'\x24\0',0x47f62f62:struct.pack('<H',1200),0x47f63922:struct.pack('<H',1200),0x47e8b568:b'\x01\0\0\0',0x47f5af40:b'\1\1'}
 for a in [0x45cffffc,0x460dfffc,0x46d7fffc,0x47bffffc,0x47f7fffc]:fields[a]=b'ENDM'
 group=bytearray(0x20000);group[0xb870]=20;group[0xb874]=4;group[0xb7e0]=88;group[0xb7e4]=77;group[-4:]=b'ENDM';fields[0x462e0000]=bytes(group)
 rows=[]
 for a,data in fields.items():
  p=g.out/f'synthetic-rom-{a:x}.bin';p.write_bytes(data);g.command+=['-device',f'loader,file={p},addr={a:#x},force-raw=on']
  rows.append(dict(address=hex(a),bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),file=p.name))
 g.data['synthetic_rom_inputs']={'hardware_calibration':False,'guest_code_modified':False,'basis':'synthetic external ROM data; not recovered factory values','rows':rows}
