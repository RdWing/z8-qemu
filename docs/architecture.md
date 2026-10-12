# Architecture

`qemu/nikon-z8-lab.c` registers `nikon-z8-lab` and its `nikon-z8-full-lab`
subtype. Nikon’s original Z8 code runs on four AArch64 CPU contexts with
QEMU 11 architectural event handling, inferred RAM, a GIC and bounded
peripheral models.

The boot and controller scripts follow original callbacks through debugger
observation points, supply GPIO and serial inputs through device contracts,
and attach synthetic ROM fixtures. Guest instructions and OS wait results
are preserved.

## Display

Scanout reads firmware-generated buffers. Requested and active framebuffer
banks are tracked separately: the active bank changes only after a valid
buffer fetch. The indexed compositor supports the observed format
`0x05030027`, channel order `0x03020100`, region clipping and ARGB palette
blending. Invalid addresses, unsupported formats and rejected strides do not
produce a completed frame.

Display-region configuration at `0x15481800..0x154819fc` and
`0x15485800..0x154859fc` retains two units’ four banks of 32 words.
This register storage does not generate pixels or interrupts by itself.

## Capture

Synthetic RGGB input, generic Bayer/NV16 processing, JPEG encoding and
PCIe/NVMe provide the experimental capture path. Nikon’s code writes the
file structure and metadata. The input fixture format uses `NZ9RAW1` magic.

The `engine1540-frame-pass-model` output stage retains its existing option
name but now encodes the actual151 packed Bayer buffer as a Nikon 14-bit
lossless stream. It uses the F0 profile’s four 2048 predictors, Bayer-parity
prediction and canonical Huffman coding. Input row padding is skipped; the
result register reports encoded bytes. Buffer capacity is enforced, and
completion is raised only after successful encoding, guest DMA and readback.
This models file-format output, not physical codec hardware or timing.

Serial configuration retains eight words per channel, including `+0x48`
read-modify-write accesses that preserve the upper half. Configuration
storage does not implement FIFO service or transfer completion.

The default-off `z8-timed-single-model` keeps an armed single request pending
while periodic DMA owns sensor input. With source bitmap `0x201`, successful
DMA invokes the existing single completion routine. Failed or absent DMA does
not complete a request. Reset, inactive-engine and retry-limit cancellation
remain in effect. This is a functional timing hypothesis.

## Movie configuration

The model retains selected configuration and request state for blocks at
`0x150d9800`, `0x150d9a00`, `0x152c0000`, `0x15ac0000`, `0x15300000`,
`0x15b00000` and `0x15648000..0x15660000`. Retained requests do not establish
DMA completion, video encoding or playable recording. The main launcher
exposes photo and menu controls.
