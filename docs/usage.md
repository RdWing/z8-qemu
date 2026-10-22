# Native display and controls

Create a synthetic input and supply explicit runtime paths:

```sh
python tools/make_cmos.py --output .local/liveview.raw
python tools/run.py --firmware /path/to/z8-main-payload.bi \
  --qemu .local/build/qemu-system-aarch64 --raw .local/liveview.raw \
  --output .local/runs/menu-001
```

The output directory must be new. Open http://127.0.0.1:8778/ and wait for
display and input readiness. The loopback controller supplies MCU packets
and displays pixels rendered into guest buffers.

Use `--smoke` for the scripted menu, submenu and return sequence.
`--check-only` verifies firmware identity and runtime file availability without
starting QEMU. Use a new output directory for each run. Result receipts record
synthetic inputs, firmware and QEMU hashes, checks and process shutdown.

The main launcher exposes photo and menu controls. Selected movie configuration
registers are modeled, but movie recording is not implemented.

Use `--card /path/to/card.raw` to keep an existing virtual exFAT card attached
across runs. Guest writes update that supplied file directly; use a copy for
experiments. Concurrent opens are rejected by QEMU's normal image locking.
Inspect and export files after the emulator stops with the capture tools.
`--experimental-playback` additionally enables the imported JPEG decode and
resize models; saved-photo guest acceptance on Z8 remains unqualified.

The Photo / Movie selector supplies byte `0x57` of the external MCU record.
Its input stays latched through every subsequent button press and release.
The displayed selection reports delivered input, not a confirmed native mode
or a working movie stream. The standard profile retains its known movie
initialization frontier. `--experimental-shared221` explicitly loads the
translated shared-device configuration described in
[the backport scope](z63-backport.md). It is a development profile, not a new
accepted default. ZR-only and Z63 attachment-clock properties are excluded.
