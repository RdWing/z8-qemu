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

## Saved-photo transfer

The optional JPEG decoder owns per-core NV16 outputs and epochs. A1 START
validates those decoded planes, finite input geometry, nonoverlapping spans
and the F4/B4 output program. It retains the input pixels, applies functional
nearest sampling and writes both destination planes before publishing input
first/data/end and B4 writer notifications. Original ISR/W1C owns retirement.
A changed decoder epoch cancels output; pending input, B4 or E ownership
prevents reuse. Explicit input STOP releases retained work without creating
output pixels. The observed B6 pulse is a timeout-path control and performs
no DMA.

For the original source-14 luma request, enabled/armed E computes 256
saturating 24-bit histogram bins from active decoded pixels, excluding pitch
padding. E cause0 follows the complete bins. This functional approximation
does not reproduce Nikon filters, physical histogram routing or timing.
Original C3.11 displays the 1620×1080 decoded preview after a 1024×682 resize
and now completes its input/histogram waits without relying on timeout
cleanup. Two normal Play/Photo/Menu cycles recover fresh pixels. Recovery after the
later idle transition and zoom retain separate acceptance.
