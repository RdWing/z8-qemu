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
