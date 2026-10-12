# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Manage one emulator process and its local runtime output."""
import json
import os
from pathlib import Path
import tempfile
from guest_transport import Transport
from probe import sha, MAIN_SHA

ROOT=Path(__file__).resolve().parent
MAIN_SHA="2b43a31c9de838f84b12416de4348a7004e65be07f853ec56ec2b10f3a8e3853"

class Guest(Transport):
    def __init__(self,firmware,binary,raw,out):
        if os.name=='nt':
            raise ValueError('Use macOS, Linux or a Linux WSL distribution')
        self.firmware=Path(firmware).resolve()
        if self.firmware.stat().st_size!=81807709 or sha(self.firmware)!=MAIN_SHA:
            raise ValueError('Expected the user-supplied Z8 C3.11 MAIN payload; see docs/firmware.md')
        self.out=Path(out).resolve();self.out.mkdir(parents=True,exist_ok=False)
        self.temp=tempfile.TemporaryDirectory(prefix='wl-z8-')
        self.runtime=Path(self.temp.name)
        self.log_path=self.out/'stderr.log';self.qtest_log_path=Path('/dev/null')
        self.ram_mib=1024;self.accelerator=None;self.intercept_irq=False
        spec=json.loads((ROOT/'model-properties.json').read_text())
        raw=Path(raw).resolve()
        if ',' in str(raw):raise ValueError('RAW path cannot contain a comma')
        machine=','.join([spec['machine'],*spec['properties'],'statistics-raw='+str(raw)])
        self.command=[str(Path(binary).resolve()),'-M',machine,'-kernel',str(self.firmware),
            '-accel','tcg,thread=single','-icount','shift=0,sleep=on',
            '-smp','4','-m','1024M','-display','none','-serial','none','-monitor','none','-S','-no-reboot',
            '-qmp',f'unix:{self.runtime}/qmp.sock,server=on,wait=off',
            '-gdb',f'unix:{self.runtime}/gdb.sock,server=on,wait=off',
            '-qtest',f'unix:{self.runtime}/qtest.sock,server=on,wait=off','-qtest-log','/dev/null']
        self.data=dict(checks=[],irq_events=[],firmware_sha256=MAIN_SHA,qemu_sha256=sha(Path(binary)),
                       raw_sha256=sha(raw),cpu_register_redirection=False,ram_patches=[],
                       classification='experimental_functional_camera_with_explicit_inputs')
        self.data['runtime_profile']=dict(clock='icount0-sleep',service_core_events=True,
            input_clock='QEMU_CLOCK_VIRTUAL',cycle_accurate=False,
            firmware_timeouts_changed=False)
        self.proc=self.qmp=self.qt=self.fp=self.gdb=None;self.irq={}
        self._log_offset=0;self._fault=False

    def log(self):
        # Service loops only need to detect strict faults. Avoid rereading a
        # growing log hundreds of times a second on a Windows-mounted path.
        with self.log_path.open('r',encoding='utf-8',errors='replace') as f:
            f.seek(self._log_offset);text=f.read();self._log_offset=f.tell()
        self._fault=self._fault or 'Z8_UNKNOWN' in text
        return 'Z8_UNKNOWN' if self._fault else ''

    def __exit__(self,kind,error,traceback):
        self.data['error']=repr(error) if error else None
        if self.proc and self.proc.poll() is None:
            try:
                self.qmp.command('quit');self.proc.wait(timeout=3)
            except Exception:
                self.proc.terminate()
                try:self.proc.wait(timeout=3)
                except Exception:self.proc.kill();self.proc.wait(timeout=3)
        self.data['owned_qemu_stopped']=self.proc is None or self.proc.poll() is not None
        (self.out/'result.json').write_text(json.dumps(self.data,indent=2)+'\n')
        for obj in (self.fp,self.qt,self.gdb):
            if obj:obj.close()
        if self.qmp:
            self.qmp.fp.close();self.qmp.sock.close()
        self.temp.cleanup()
