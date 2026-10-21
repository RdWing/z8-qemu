# Native Z8 HE stills

Original Z8 C3.11 MAIN with a declared host controller peer can save one HE or
HE★ NEF per cold boot with the opt-in
functional HE receiver and explicit synthetic sensor/ROM preparation inputs.
The original-EX attachment has separate [capture acceptance](native-mcu.md);
these host-peer results do not transfer to it.
The guest constructs the file and writes the virtual card. The host extracts
initialized file bytes without repairing or replacing the container.

| Original RAW recording choice | NEF label | File bytes | RAW strip bytes |
| --- | ---: | ---: | ---: |
| High efficiency★ | 14 | 29,324,288 | 28,565,504 |
| High efficiency | 13 | 17,897,984 | 17,139,200 |

Both strips start at byte 758,784 and decode all 45,705,600 samples at
8280×5520. The supplied 320×240 RGGB fixture is expanded by Bayer-cell
resampling with conversion `min(16383,(v*16383+2047)//4095)`. Maximum error
is 26 and mean absolute error 3.029557 on the 14-bit scale. Both modes decode
identically for this simple fixture; this does not compare photographic quality.
Regular HE's saved strip exactly matches the receiver DMA snapshot, and its
packed14 producer matches all scaled sensor samples. The embedded 160×120,
640×424 and 8256×5504 JPEGs also decode.

The finite FIFO writes the complete HE buffer before data causes 6. After
original W1C, the native driver holds the receiver and requests STOP. The model
requires acknowledged HE output, no pending data owners and a stopped primary
source before posting end cause 8. Original W1C retires that stop. It is separate
from the continuous movie receiver's drain contract. Its timer starts only on
STOP, preserving pre-capture scheduling. Source tests reject early and duplicate
stop requests and preserve unrelated pending causes.

Use the existing capture command with `--experimental-he-still` and the three
explicit preparation/selector/timed-single flags. The default native setting is
HE★; regular HE uses the menu sequence in `tools/he-capture-profiles.json`.
All firmware, sensor frames, virtual cards and output directories remain local.

Build the bounded read-only decoder with a C++17 compiler:

```sh
c++ -std=c++17 -O2 -I qemu -I qemu/nikon-he-public \
  tools/decode_he.cpp qemu/nikon-he-runtime.cpp qemu/nikon-he-public/*.cpp \
  -o /path/to/decode_he
python3 tools/audit_he_nef.py /path/to/DSC_0001.NEF \
  --output /path/to/new-audit --decoder /path/to/decode_he --previews
python3 tools/audit_he_pixels.py --run /path/to/capture-run \
  --audit /path/to/new-audit --raw /path/to/synthetic.raw
```

The container audit needs ExifTool, preview decoding needs Pillow, and the pixel
comparison needs NumPy. The codec is an authored functional forward model and a
pinned public inverse. Nikon encoder microcode, physical ISP/color equivalence,
repeat captures, post-capture recovery, movie recording and physical-camera
quality remain unqualified. Stock LibRaw builds may lack the HE decode path;
opening previews alone is not RAW decoding.
