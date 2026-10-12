# Experimental Z8 RAW capture

The capture workflow requires three explicit experimental options and
selects **RAW → Lossless compression** through Nikon’s original menu.
High efficiency★ reached an unsupported RAW destination. The functional
packed-14 model does not implement Nikon’s proprietary lossless codec.

Install exfatprogs (`mkfs.exfat`, `fsck.exfat`) and, for independent audit,
ExifTool and `requirements-capture.txt` in addition to the base requirements.
On macOS, make the exfatprogs executables available on PATH. No host block
device is formatted: card creation requires a fresh regular file.

```sh
python -m pip install -r requirements-capture.txt
python tools/make_cmos.py --capture --output .local/sensor-14bit.raw
python tools/make_card.py --output .local/blank-card.raw
python tools/capture.py --firmware /path/to/z8-main-payload.bi \
  --qemu .local/build/qemu-system-aarch64 --raw .local/sensor-14bit.raw \
  --card-template .local/blank-card.raw --output .local/runs/capture-001 \
  --seconds 600 --settle 120 \
  --experimental-preparation-profile --experimental-capture-selector5 \
  --experimental-timed-single \
  --menu-actions 'menu,down,down,down,down,down,down,down,down,down,down,ok,up,ok,menu,menu'
```

The card is 8 GiB, with an MBR/exFAT partition beginning at byte 1,048,576.
The harness copies that template into the fresh output directory, attaches
NVMe to DesignWare PCIe, follows native preparation/shutter handling, and
records model state. Source and sensor input are explicit functional substitutes.
Button presses remain short to avoid repeated navigation.

After the owned emulator has stopped, inspect and extract the actual guest
file. The observed first-capture path is `DCIM/100NCZ_8/DSC_0001.NEF`; use the
actual catalog if the guest chooses a different directory.

```sh
python -c "import sys; sys.path.insert(0,'tools'); from inspect_card_volume import catalog; print(catalog('.local/runs/capture-001/capture-card.raw',1048576))"
python tools/extract_card_file.py \
  --volume .local/runs/capture-001/capture-card.raw \
  --file DCIM/100NCZ_8/DSC_0001.NEF \
  --output .local/runs/capture-001/DSC_0001.NEF
python tools/audit_nef.py --output .local/runs/capture-001 \
  --firmware /path/to/z8-main-payload.bi --raw .local/sensor-14bit.raw
```

The audit checks extraction integrity, all RAW samples against the supplied
synthetic input, the available guest RAW producer snapshot, metadata and three
JPEG previews. Each run records the supplied input hash and uses that input for comparison.

Auto and Standard outputs have been independently decoded. Repeat the complete
workflow to qualify a new build. Repeated shooting,
burst capture, robust post-shot recovery and preview-to-encoder byte matching
remain open.
