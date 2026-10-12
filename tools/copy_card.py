# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Copy a fresh regular-file card, preserving holes when the host supports it."""
import errno,os,shutil
from pathlib import Path
def copy_card(source,target):
    source,target=Path(source),Path(target)
    with source.open('rb') as src,target.open('xb') as dst:
        size=source.stat().st_size;dst.truncate(size)
        if hasattr(os,'SEEK_DATA'):
            position=0
            try:
                while position<size:
                    try:start=os.lseek(src.fileno(),position,os.SEEK_DATA)
                    except OSError as e:
                        if e.errno==errno.ENXIO:return
                        raise
                    end=min(size,os.lseek(src.fileno(),start,os.SEEK_HOLE))
                    src.seek(start);dst.seek(start);left=end-start
                    while left:
                        block=src.read(min(left,1024*1024))
                        if not block:raise EOFError('Short card template')
                        dst.write(block);left-=len(block)
                    position=end
                return
            except OSError as e:
                if e.errno not in (errno.EINVAL,errno.ENOTSUP):raise
        src.seek(0);dst.seek(0);shutil.copyfileobj(src,dst,1024*1024)
