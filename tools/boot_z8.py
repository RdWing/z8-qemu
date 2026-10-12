# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Version-pinned boot with explicit virtual ROM and MCU inputs.

Hardware breakpoints sequence the incomplete GPIO peer. They do not replace
instructions, guest RAM, PC, task results, readiness flags or watchdogs.
"""
import re
import struct
import time
from deliver_mcu_frame import deliver
from receive_mcu_tx import receive
from mcu_frames import frames,status_body
from probe_adc_capture import at
from probe_tasks import settle

def key_body(menu=False,half=False):
    data=bytearray(124);data[0]=data[4]=1;data[0x43]=int(menu);data[7]=int(half)
    return bytes(data)

def observe(g,points):
    pending=set(points)
    for pc in pending:g.rsp(f'Z1,{pc:x},4')
    deadline=time.monotonic()+30
    try:
        while pending and time.monotonic()<deadline:
            g.qmp.command('cont')
            while g.qmp.command('query-status')['running'] and time.monotonic()<deadline:time.sleep(.01)
            g.qmp.command('stop')
            if 'Z8_UNKNOWN' in g.log():raise RuntimeError('Unmodeled hardware access during boot')
            for cpu in range(4):
                pc=int(re.search(r'\bPC=([0-9a-fA-F]+)',g.qmp.hmp('info registers',cpu))[1],16)
                if pc in pending:g.rsp(f'z1,{pc:x},4');pending.remove(pc)
        if pending:raise TimeoutError('Original boot callbacks missing: '+str(sorted(pending)))
    finally:
        for pc in pending:g.rsp(f'z1,{pc:x},4')

def boot(g,progress=print):
    progress('Booting original firmware')
    g.rsp('z1,40160000,4');at(g,0x4033db98)
    deliver(g,frames(status_body({0x1c:2}))[0],prefix='power-')
    _,r=at(g,0x40d57a90)
    g.check('original power status accepted',r['X01']==0x03040002)
    _,r=at(g,0x40d67260)
    g.check('original system power event',r['X00']==0x05020101)
    settle(g,1)
    body=bytearray(112);body[0]=3
    deliver(g,frames(body,family=4)[0],prefix='battery-')
    at(g,0x41181504)
    for index in range(32):
        wire=receive(g,prefix=f'boot-out-{index:02d}-')
        if wire[0]==13 and wire[8] in (1,2,3,4):
            body=bytearray(16);body[0]=0x80|wire[8];body[4]=wire[12]
            deliver(g,frames(body,family=13)[0],prefix=f'boot-lens-{index:02d}-')
            _,r=at(g,0x4106e690)
            payload=g.read_bytes(r['X01'],8)
            g.check('original lens controller accepts reply',struct.unpack_from('<I',payload)[0]==0)
            if payload[4]==0:break
    else:raise RuntimeError('Lens controller startup did not complete')
    observe(g,(0x40d66034,0x40d55da0,0x40d5eb7c))
    deliver(g,frames(key_body(half=True),family=2)[0],prefix='boot-key-')
    observe(g,(0x40d271e4,0x40d26d7c,0x40d3003c,0x40fac9bc,0x40d57118))
    body=bytearray(16);body[0]=1
    deliver(g,frames(body,family=9)[0],prefix='boot-ccomp-')
    progress('Starting original display and functional sensor input')
