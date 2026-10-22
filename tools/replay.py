# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Replay external controls against virtual guest time after native menu readiness."""
import json
import threading
from control import BUTTONS

class Replay:
    def __init__(self, path):
        self.actions = json.loads(path.read_text())
        if not isinstance(self.actions, list) or not self.actions:
            raise ValueError('Replay requires a nonempty action list')
        previous = -1
        for row in self.actions:
            if set(row) != {'after', 'kind', 'value'}:
                raise ValueError('Replay actions require after, kind and value')
            after = row['after']
            if type(after) not in (int, float) or not 0 <= after <= 3000 or after < previous:
                raise ValueError('Replay times must be ordered finite seconds in 0..3000')
            previous = after
            if not (row['kind'] == 'mode' and row['value'] in ('photo', 'movie') or
                    row['kind'] == 'button' and row['value'] in BUTTONS):
                raise ValueError('Unknown replay control')
        self.stop = threading.Event()
        self.ready = False
        self.shooting_mode = 'photo'
        self.start = None
        self.now = 0
        self.index = self.sent = 0
        self.capture_at = None
        self.captured = []
    def publish(self, frame, row, ready):
        self.now = row['virtual_seconds']
        if self.capture_at is not None and self.now >= self.capture_at:
            target=frame.with_name(f'replay-{self.sent:03d}.ppm')
            target.write_bytes(frame.read_bytes())
            self.captured.append(dict(file=target.name,virtual_seconds=self.now,sent=self.sent))
            self.capture_at=None
        self.ready = ready or self.start is not None
        if ready and self.start is None:
            self.start = self.now
    def next_input(self):
        if self.start is None or self.index == len(self.actions):
            return None
        row = self.actions[self.index]
        if self.now - self.start < row['after']:
            return None
        self.index += 1
        value = BUTTONS[row['value']] if row['kind'] == 'button' else row['value']
        return row['kind'], value
    def mark_sent(self):
        self.sent += 1
        self.capture_at=self.now+4
    def status(self):
        return dict(ready=self.ready, replay=True, sent=self.sent, total=len(self.actions),
                    shooting_mode=self.shooting_mode, start_virtual_seconds=self.start, captures=self.captured)
    def close(self):
        pass
