# SPDX-License-Identifier: GPL-2.0-or-later
# Copyright (C) 2026 RdWing
"""Generate fresh synthetic RGGB bars in the shared NZ9RAW1 input format."""
import argparse,struct
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--output',type=Path,required=True);p.add_argument('--capture',action='store_true')
a=p.parse_args();w,h,bits=(8256,5504,14) if a.capture else (640,480,12)
white=(1<<bits)-1
bars=np.array([[1,1,1],[1,1,0],[0,1,1],[0,1,0],[1,0,1],[1,0,0],[0,0,1],[0,0,0]],dtype=np.float64)
row=bars[np.arange(w)*8//w];a.output.parent.mkdir(parents=True,exist_ok=True)
with a.output.open('xb') as f:
    f.write(struct.pack('<8s6I',b'NZ9RAW1\0',w,h,bits,0,0,white))
    for y in range(h):
        rgb=row*(.25+.75*y/(h-1));linear=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
        out=np.empty(w,dtype='<u2')
        out[0::2]=np.rint(linear[0::2,0 if y%2==0 else 1]*white)
        out[1::2]=np.rint(linear[1::2,1 if y%2==0 else 2]*white)
        f.write(out.tobytes())
print(a.output)
