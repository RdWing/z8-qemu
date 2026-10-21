# RdWing Z8 QEMU

[Build](docs/build.md) · [Firmware](docs/firmware.md) · [Usage](docs/usage.md) · [RAW capture](docs/capture.md) · [Architecture](docs/architecture.md) · [Testing](docs/testing.md) · [Z63 backport](docs/z63-backport.md)

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

## Z8 additions over the Z9 base

Compared with the upstream revision linked above, this adaptation adds:

- **Boot and controls:** Z8 C3.11 [hardware mappings](qemu/nikon-z8-lab.c), [boot sequence](tools/boot_z8.py#L38) and [controller/menu bindings](tools/z8_navigation_input.py#L11).
- **Display:** [framebuffer-bank switching](qemu/nikon-z8-lab.c#L4679), [active-bank acknowledgement](qemu/nikon-z8-lab.c#L15411) and [indexed palette overlays](qemu/nikon-z8-lab.c#L4628).
- **Capture:** Z8 [preparation inputs](tools/capture.py#L36), [display-region](qemu/nikon-z8-lab.c#L4004)/[serial register retention](qemu/nikon-z8-lab.c#L7127) and [timed single-frame completion fixes](qemu/nikon-z8-d980.h#L179) enabling full NEF capture, with [Nikon lossless14 encoding](qemu/nikon-z8-lossless.h) of the guest-produced Bayer data.
- **Movie mode:** additional [configuration-register retention and initialization handling](qemu/nikon-z8-lab.c#L6975); recording remains incomplete; shared-device source ports and their remaining target gaps are listed in the backport scope.
- **Tooling:** [QEMU 11 compatibility](qemu/prepare_source.py), [portable Z8 launchers](tools/run.py), [macOS builds](tools/build.py#L28)/[card creation](tools/virtual_recording_card.py#L65) and [adapted NEF auditing](tools/audit_nef.py).

The underlying RAW/JPEG and NVMe capture infrastructure is inherited from Z9.

## Current scope

| Implemented or observed on Z8 | Qualification |
| --- | --- |
| Original menus, shooting HUD, controller input and four AArch64 CPU contexts | Synthetic boot and peripheral inputs; selected paths tested. |
| Selected native graphics, four framebuffer banks and indexed palette overlays | Functional rendering; physical AF and display color accuracy remain open. |
| Synthetic RGGB input, functional Bayer/NV16 processing and JPEG previews | Generic processing; Nikon ISP, HE/HE* and physical codec hardware are not reproduced. Functional HE is now available as an opt-in imported model, with native Z8 HE/HE* acceptance still open. |
| Firmware-written 8280 × 5520, 14-bit NEFs on virtual NVMe/exFAT | LibRaw and Adobe decoding checked all 45,705,600 samples. Capture requires three explicit experimental options and the Lossless menu setting. |
| Picture Control metadata and Camera Raw defaults | Metadata inspected for Auto and Standard; lossless decoding checked with Auto. |
| Movie configuration registers and selector handling | Movie initialization remains incomplete; playable recording and physical AF/lens drive are unqualified. |

A complete QEMU build, native menu navigation and single NEF capture have
passed on macOS. LibRaw and Adobe DNG Converter independently decoded every
RAW sample with zero mismatches; all three JPEG previews also decoded. Source
and model-contract checks cover the display renderer and selected peripheral
behavior. Repeated shooting and post-shot recovery
remain open.

The cumulative Z63 C2.00/C2.01 shared-device changes are adapted through
`5c3b47c`, including functional HE, JPEG provenance/cancellation, playback resize,
capture ownership and video-domain models. This is a **partial feature backport**:
Z8 native HE/movie/playback parity, Z8 MCU integration and the native desktop
frontend remain unqualified or unimplemented. Existing lossless capture is
preserved and freshly accepted by LibRaw and Adobe. See the
[feature disposition and checks](docs/z63-backport.md) before enabling the
experimental profile.

## Quick start

Use macOS or Linux, Python 3.12+, a C toolchain, Ninja, pkg-config, GLib,
Pixman, zlib, libfdt, libjpeg, x264, x265 and a C++17 compiler. Linux card creation needs exfatprogs; macOS uses native exFAT tools.
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
