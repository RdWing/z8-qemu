# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Read Z8 original GPIO objects resolved through disassembled getters."""
import struct

def capture(g):
 def read(a,n):return g.read_bytes(a,n)
 table=int.from_bytes(read(0xa02afcfe8,8),'little')
 assert 0x40160000<=table<0x45000000,hex(table)
 with g.firmware.open('rb') as f:f.seek(table-0x40160000);logical=f.read(0x2c*4)
 rows=[]
 for ident in (0x23,0x24,0x27,0x28,0x26,0x2b):
  index=struct.unpack_from('<I',logical,ident*4)[0];assert index<512
  ptr=int.from_bytes(read(0xa02afc000+index*8,8),'little');assert 0xa00000000<=ptr<0xa20000000
  desc=read(ptr,0x30);bank,bit=struct.unpack_from('<II',desc,4);irq=struct.unpack_from('<Q',desc,0x20)[0]
  assert not irq or 0xa00000000<=irq<0xa20000000
  rows.append(dict(logical=ident,index=index,pointer=hex(ptr),bank=bank,bit=bit,descriptor_hex=desc.hex(),irq_hex=read(irq,0x40).hex() if irq else None))
 g.data['z8_gpio_bindings']={'table':hex(table),'rows':rows}
 return rows
