# RdWing Z8 QEMU

[Build](docs/build.md) · [Firmware](docs/firmware.md) · [Usage](docs/usage.md) · [RAW capture](docs/capture.md) · [Architecture](docs/architecture.md) · [Testing](docs/testing.md)

An experimental **QEMU 11.1.1** machine for **Nikon Z8 C3.11**, adapted from
[WonderLantern’s Z9 emulator](https://github.com/WonderLantern/z9-qemu) at
`deb3a75df1795924e9be8f814d9a24ce6b439a67`.

The model runs Nikon’s original menu and shooting tasks, accepts controller
inputs, renders framebuffer banks and indexed overlays, and supports
experimental NEF capture to a virtual NVMe/exFAT card.
See [NOTICE.md](NOTICE.md) for attribution and licensing.

**Bring your own firmware.** Firmware, calibration, card images, captured
NEFs, screenshots, recordings and compiled emulator binaries are not included.
The tools generate synthetic sensor and card inputs.

## Current scope

| Implemented or observed on Z8 | Qualification |
| --- | --- |
| Original menus, shooting HUD, controller input and four AArch64 CPU contexts | Synthetic boot and peripheral inputs; selected paths tested. |
| Selected native graphics, four framebuffer banks and indexed palette overlays | Functional rendering; physical AF and display color accuracy remain open. |
| Synthetic RGGB input, functional Bayer/NV16 processing and JPEG previews | Generic models; Nikon ISP and proprietary RAW codecs are not reproduced. |
| Firmware-written 8280 × 5520, 14-bit NEFs on virtual NVMe/exFAT | Independent decoding checked all 45,705,600 samples. Capture requires three explicit experimental options and the Lossless menu setting. |
| Picture Control metadata and Camera Raw defaults | Auto and Standard outputs inspected. |
| Movie configuration registers and selector handling | Movie initialization remains incomplete; playable recording and physical AF/lens drive are unqualified. |

A complete QEMU build, native menu navigation and single NEF capture have
passed on macOS. Independent auditing checked every RAW sample and all three
JPEG previews. Source and model-contract checks cover the display renderer
and selected peripheral behavior. Repeated shooting and post-shot recovery
remain open.

## Quick start

Use macOS or Linux, Python 3.12+, a C toolchain, Ninja, pkg-config, GLib,
Pixman, zlib, libfdt and libjpeg. Linux card creation needs exfatprogs; macOS uses native exFAT tools.
Supply a separate **QEMU 11.1.1** source tree.

```sh
python3 -m venv .local/venv
. .local/venv/bin/activate
python -m pip install -r requirements.txt
python tools/build.py --qemu-source /path/to/qemu-11.1.1 \
  --build-dir .local/build --jobs 2
python tools/make_cmos.py --output .local/liveview.raw
python tools/run.py --firmware /path/to/z8-main-payload.bi \
  --qemu .local/build/qemu-system-aarch64 --raw .local/liveview.raw \
  --output .local/runs/menu-001
```

Open **http://127.0.0.1:8778/** after the original display starts. MENU,
directional keys, OK and half-shutter go through the native controller path.
The page’s stop control or Ctrl+C ends the emulator.

For checks without firmware:

```sh
python tests/run.py
python tools/audit_source.py
```

For experimental capture, follow [docs/capture.md](docs/capture.md).

## Layout

```text
qemu/       Z8 camera source, headers and QEMU integration helper
tools/      Boot, controller, display, capture and audit scripts
docs/       Build, usage, architecture and testing documentation
tests/      Source checks, scanout tests and hardware contracts
.local/     Ignored runtime data and build outputs
```

The machine types are `nikon-z8-lab` and `nikon-z8-full-lab`.
The shared `NZ9RAW1` fixture magic identifies the input format used by the
inherited parser.
