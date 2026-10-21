# Building

Supply a separate QEMU **11.1.1** source checkout or extraction.
Install a C toolchain, Python 3.12+, Ninja, pkg-config, GLib, Pixman, zlib,
libfdt, libjpeg, x264 and x265 development files, plus a C++17 compiler. Python requirements are separate from
QEMU’s build dependencies. On macOS the builder disables QEMU’s unrelated
paravirtualized graphics device, whose APIs are unavailable in recent SDKs.

```sh
python qemu/prepare_source.py /path/to/qemu-11.1.1 --check
python tools/build.py --qemu-source /path/to/qemu-11.1.1 \
  --build-dir .local/build --jobs 2
```

The integration helper validates the version and plans all changes before
writing. It installs the Z8 overlay and included HE runtime, enables device dependencies,
libjpeg, x264/x265 and the C++ runtime, and applies the DesignWare DMA and SMP breakpoint fixes.
Existing source inputs are preserved under `.z8-qemu-backup/` in the selected
QEMU tree. Unexpected source context or independently edited Z8 files stop preparation. An overlay can be upgraded only when the destination still matches its previous installation receipt.

Use a fresh source tree and a dedicated build directory. Repeating preparation
with unchanged inputs is supported. Build output and its receipt remain in
the supplied build directory. QEMU’s configure step may fetch its dependencies.

A complete QEMU 11.1.1 build has passed on macOS. Use the boot and capture
workflows to qualify a new binary or host environment.
