# Experimental Z8 RAW capture

The capture workflow requires three explicit experimental options and
selects **RAW → Lossless compression** through Nikon’s original menu.
High efficiency★ reached an unsupported RAW destination. The output stage
encodes the guest-produced Bayer buffer as a Nikon 14-bit lossless stream,
matching the firmware’s F0 metadata and four 2048 predictor seeds. This is a
bounded file-format model; physical codec hardware and HE/HE* remain unmodeled.

On Linux, install exfatprogs (`mkfs.exfat`, `fsck.exfat`). macOS uses its native
`newfs_exfat` and `fsck_exfat` utilities through a temporary, unmounted disk
image. Only the newly created regular image is attached and formatted, then
detached; physical disks are not selected. For independent audit, install
ExifTool and `requirements-capture.txt` in addition to the base requirements.

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
synthetic input, the required guest RAW producer snapshot, metadata and three
JPEG previews. It rejects the packed-size fallback that can make LibRaw accept
uncompressed bytes under a Nikon-compressed tag. Each run records the supplied
input hash and uses that input for comparison.

For a second decoder, convert the captured NEF with Adobe DNG Converter, then
pass its DNG to the same audit:

```sh
python tools/audit_nef.py --output .local/runs/capture-001 \
  --firmware /path/to/z8-main-payload.bi --raw .local/sensor-14bit.raw \
  --adobe-dng /path/to/DSC_0001.dng
```

This compares the DNG’s underlying RAW samples, not its preview. The audit
reports `full_file_accepted` only when this second-decoder comparison passes.

Earlier packed-copy outputs could have correct previews and metadata while
rendering garbled RAW data in Adobe. Their LibRaw sample checks used its
uncompressed-size fallback and did not establish lossless-format validity.
Recapture those files with the lossless encoder.

The lossless workflow has been checked with Picture Control Auto. Repeat the
complete workflow to qualify other settings or a new build. Repeated shooting,
burst capture, robust post-shot recovery and preview-to-encoder byte matching
remain open.
