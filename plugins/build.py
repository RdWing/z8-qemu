# SPDX-License-Identifier: GPL-2.0-or-later
"""Build the optional read-only trace plugin against a matching QEMU 11 SDK."""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--qemu-source',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();sdk=a.qemu_source.resolve()/'include/plugins'
    if not (sdk/'qemu-plugin.h').is_file():p.error('Expected QEMU 11 include/plugins/qemu-plugin.h')
    output=a.output.resolve()
    if output.exists():p.error('Choose a new plugin output file')
    output.parent.mkdir(parents=True,exist_ok=True)
    flags=['-dynamiclib','-undefined','dynamic_lookup'] if sys.platform=='darwin' else ['-shared']
    cflags=shlex.split(subprocess.check_output(['pkg-config','--cflags','glib-2.0'],text=True))
    libs=[] if sys.platform=='darwin' else shlex.split(subprocess.check_output(['pkg-config','--libs','glib-2.0'],text=True))
    subprocess.run([os.environ.get('CC','cc'),'-std=c11','-O2','-fPIC','-fvisibility=hidden',
        '-Wall','-Wextra','-Werror',*flags,'-I'+str(sdk),*cflags,str(Path(__file__).with_name('z8trace.c')),
        '-o',str(output),*libs],check=True)
    print(output)


if __name__=='__main__':main()
