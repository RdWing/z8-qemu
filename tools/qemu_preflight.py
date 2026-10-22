# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Check a selected QEMU executable with --version, without opening firmware."""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

DEFAULT_TIMEOUT = 10.0


def _stop(process):
    """Reap this check's private group, including an unresponsive descendant."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=.25)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait(timeout=1)


def check(qemu, *, timeout=DEFAULT_TIMEOUT, cancelled=None):
    """Return only --version completion evidence; this does not boot a machine."""
    if os.name == 'nt':
        raise ValueError('QEMU preflight requires macOS, Linux or a Linux WSL distribution')
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 60:
        raise ValueError('QEMU check timeout must be greater than zero and at most 60 seconds')
    if cancelled and cancelled():
        raise InterruptedError('QEMU executable check cancelled; no firmware session was started')
    binary = Path(qemu)
    if not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK):
        raise ValueError('qemu must name an existing absolute executable file')
    started = time.monotonic()
    process = subprocess.Popen([str(binary), '--version'], stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    try:
        while True:
            if cancelled and cancelled():
                raise InterruptedError('QEMU executable check cancelled; no firmware session was started')
            status = process.poll()
            if status is not None:
                if status:
                    raise RuntimeError(f'QEMU --version exited with status {status}; no firmware session was started')
                return dict(elapsed_seconds=round(time.monotonic()-started, 6), process_status=status,
                            qualification='QEMU --version only; firmware and machine startup were not tested')
            if time.monotonic()-started >= timeout:
                hint = ' On macOS, try a stable QEMU runtime outside Documents.' if sys.platform == 'darwin' else ''
                raise TimeoutError(f'QEMU --version did not finish within {timeout:g} seconds; no firmware session was started.'+hint)
            time.sleep(min(.02, timeout))
    finally:
        _stop(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qemu', type=Path, required=True)
    parser.add_argument('--timeout', type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()
    stopping = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopping.set())
    try:
        print(json.dumps(check(args.qemu, timeout=args.timeout, cancelled=stopping.is_set)))
    except InterruptedError as error:
        parser.exit(130, str(error)+'\n')
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, str(error)+'\n')


if __name__ == '__main__':
    main()
