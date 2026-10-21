# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Own one desktop child session and stop its complete private process group."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
FLAGS = ('experimental_playback', 'experimental_shared221')


def command(config):
    allowed = {'python', 'firmware', 'qemu', 'raw', 'output', 'card', 'mcu', 'seconds', *FLAGS}
    if not isinstance(config, dict) or set(config) - allowed:
        raise ValueError('Unknown desktop configuration fields')
    native=bool(config.get('mcu'))
    args = [sys.executable, '-u', str(ROOT/'tools'/('run_native.py' if native else 'run.py'))]
    if native:
        mcu=config['mcu']
        if not isinstance(mcu,str) or not Path(mcu).is_absolute() or not Path(mcu).is_file():
            raise ValueError('mcu must name an existing absolute EX component')
        if config.get('card') or any(config.get(k) for k in FLAGS):
            raise ValueError('Native MCU display mode currently requires card/playback/shared-profile options to be omitted')
        args += ['--mcu',mcu]
    for key in ('firmware', 'qemu', 'raw', 'output'):
        value = config.get(key)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError(f'{key} must be an absolute path')
        if key != 'output' and not Path(value).is_file():
            raise ValueError(f'{key} does not name a file')
        if key == 'output' and Path(value).exists():
            raise ValueError('Choose a new output directory for this session')
        args += ['--'+key, value]
    if config.get('card'):
        value = config['card']
        if not isinstance(value, str) or not Path(value).is_absolute() or not Path(value).is_file():
            raise ValueError('card must name an existing absolute file')
        args += ['--card', value]
    seconds = config.get('seconds', 3600)
    if type(seconds) is not int or not 1 <= seconds <= 3600:
        raise ValueError('seconds must be an integer from 1 to 3600')
    args += ['--seconds', str(seconds), '--port', '0']
    for flag in FLAGS:
        if type(config.get(flag, False)) is not bool:
            raise ValueError(flag+' must be true or false')
        if config.get(flag):
            args += ['--'+flag.replace('_', '-')]
    if config.get('experimental_playback') and not config.get('card'):
        raise ValueError('Playback requires an existing card image')
    return args


def stop_child(child, grace=8):
    """Signal only our new process group; include QEMU even if boot is pending."""
    try:
        child.terminate()
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=3)
    # The launcher can exit before an inherited QEMU. The group belongs only
    # to this session because Popen created it with start_new_session=True.
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--check-only', action='store_true')
    a = parser.parse_args()
    config = json.loads(a.config.read_text())
    args = command(config)
    if a.check_only:
        subprocess.run(args + ['--check-only'], check=True)
        return
    stopping = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stopping.set())
    out = Path(config['output'])
    out.parent.mkdir(parents=True, exist_ok=True)
    # Keep the launcher log beside the result directory without pre-creating
    # that directory (the guest owns its exclusive creation).
    log = out.with_name(out.name+'.desktop.log')
    if log.exists():
        raise ValueError('Desktop log already exists; choose a new output path')
    child = None
    try:
        with log.open('xb') as stream:
            child = subprocess.Popen(args, stdout=stream, stderr=stream, start_new_session=True)
        ready = False
        while child.poll() is None and not stopping.wait(.1):
            endpoint = out/'control-endpoint.json'
            if not ready and endpoint.exists():
                data = json.loads(endpoint.read_text())
                print(json.dumps(dict(event='ready', **data)), flush=True)
                ready = True
        if not stopping.is_set() and child.returncode:
            raise RuntimeError(f'Emulator exited with status {child.returncode}; see {log}')
    finally:
        if child:
            stop_child(child)
        print(json.dumps(dict(event='stopped', output=str(out), log=str(log))), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps(dict(event='error', message=str(error))), flush=True)
        raise SystemExit(1)
