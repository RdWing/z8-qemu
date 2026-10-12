# Building

Supply a separate QEMU **11.1.1** source checkout or extraction.
Install a C toolchain, Python 3.12+, Ninja, pkg-config, GLib, Pixman, zlib,
libfdt and libjpeg development files. Python requirements are separate from
QEMU’s build dependencies.

```sh
python qemu/prepare_source.py /path/to/qemu-11.1.1 --check
python tools/build.py --qemu-source /path/to/qemu-11.1.1 \
  --build-dir .local/build --jobs 2
```

The integration helper validates the version and plans all changes before
writing. It installs eight Z8 source files, enables device dependencies and
libjpeg, and applies the DesignWare DMA and SMP breakpoint fixes.
Existing source inputs are preserved under `.z8-qemu-backup/` in the selected
QEMU tree. Unexpected source context or divergent Z8 files stop preparation.

Use a fresh source tree and a dedicated build directory. Repeating preparation
with unchanged inputs is supported. Build output and its receipt remain in
the supplied build directory. QEMU’s configure step may fetch its dependencies.

The camera model has compiled without warnings against QEMU 11 generated
headers. A complete build and runtime qualification are required for a new
QEMU installation.
