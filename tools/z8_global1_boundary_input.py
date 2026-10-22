# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Explicit diagnostic external boundary inputs, independent of guest PC.

QEMU virtual time determines delivery intervals; host polling may delay them.
This is neither a measured CMOS clock nor an image job completion. Missed
periods are dropped, never delivered as a catch-up burst.
"""
from pathlib import Path
import json
import time
from probe import sha


class Peer:
    def __init__(self, guest, period_ms, *, auxiliary_masked=False, auxiliary1_masked=False, global0_bit26=False):
        if not 10 <= period_ms <= 1000:
            raise ValueError('bounded virtual diagnostic input period required')
        self.g = guest
        self.period = period_ms / 1000
        self.started = None
        self.next_at = None
        self.auxiliary_masked = auxiliary_masked
        self.auxiliary1_masked = auxiliary1_masked
        self.global0_bit26 = global0_bit26
        self.host_started = time.monotonic()
        self.record = dict(classification='diagnostic_periodic_external_status',
            source_sha256=sha(Path(__file__)), period_ms=period_ms, clock='QEMU_CLOCK_VIRTUAL',
            endpoint='event1508-global1-input', mask=128, deliveries=[], limit=4096,
            total_deliveries=0, clock_stepped=False, limit_scope='saved delivery records only',
            scheduled_at_guest_wait=False, uses_guest_PC=False, pixel_bytes=0,
            physical_timing_verified=False, camera_acceptance=False)
        self.record['auxiliary_masked'] = auxiliary_masked
        self.record['auxiliary1_masked'] = auxiliary1_masked
        self.record['global0_bit26'] = global0_bit26
        self.record['auxiliary1_deliveries'] = 0
        self.record['global0_bit26_deliveries'] = 0
        self.record['auxiliary_deliveries'] = 0
        self.record['auxiliary_bit0'] = 0
        self.record['auxiliary_bit1'] = 0
        guest.data['diagnostic_global1_boundary_input'] = self.record
        (guest.out/'global1-boundary-peer-source.py').write_bytes(Path(__file__).read_bytes())

    def tick(self):
        clock=json.loads(self.g.qmp.command('qom-get',path='/machine',property='runtime-clock-state'))
        if not clock['running']:
            return
        now = clock['virtual_ns']/1e9
        if self.started is None:
            self.started = now
            self.next_at = now
        if now < self.next_at:
            return
        self.g.qmp.command('qom-set', path='/machine', property=self.record['endpoint'], value='128')
        if self.auxiliary_masked:
            state=json.loads(self.g.qmp.command('qom-get',path='/machine',property='event1508-aux0-state'))
            mask=state['mask'] & 3
            if state['enabled'] and mask:
                self.g.qmp.command('qom-set',path='/machine',property='event1508-aux0-input',value=str(mask))
                self.record['auxiliary_deliveries']+=1
                self.record['auxiliary_bit0']+=bool(mask & 1)
                self.record['auxiliary_bit1']+=bool(mask & 2)
        if self.auxiliary1_masked:
            state=json.loads(self.g.qmp.command('qom-get',path='/machine',property='event1508-aux1-state'))
            mask=state['mask'] & 3
            if state['enabled'] and mask:
                self.g.qmp.command('qom-set',path='/machine',property='event1508-aux1-input',value=str(mask))
                self.record['auxiliary1_deliveries']+=1
        if self.global0_bit26:
            self.g.qmp.command('qom-set',path='/machine',property='event1508-global0-input',value=str(1<<26))
            self.record['global0_bit26_deliveries']+=1
        if len(self.record['deliveries']) < self.record['limit']:
            self.record['deliveries'].append(dict(index=self.record['total_deliveries'],
                elapsed_host_seconds=time.monotonic()-self.host_started,
                elapsed_virtual_seconds=now-self.started,virtual_ns=clock['virtual_ns']))
        else:
            self.record['record_limit_reached']=True
        self.record['total_deliveries']+=1
        self.record['last_virtual_ns']=clock['virtual_ns']
        self.next_at = now+self.period
