# Research and rights notice

This project adapts WonderLantern’s independent Z9 QEMU emulator at commit
`deb3a75df1795924e9be8f814d9a24ce6b439a67`. The hardware model, image-processing
and storage helpers, and reused tools retain their upstream attribution and
licensing.

Copyright (C) 2026 RdWing applies to the Z8 adaptations and new code identified
in source comments. These notices supplement existing notices; they do not
claim authorship of inherited algorithms.

The overlay and tools use GPL-2.0-or-later. Preserve existing copyright notices,
SPDX identifiers and attribution. QEMU retains its upstream licensing; see
[COPYING](COPYING) and [LICENSES/QEMU-LICENSE.txt](LICENSES/QEMU-LICENSE.txt).
The DesignWare DMA and SMP breakpoint fixes are adapted upstream requirements.

The lossless encoder implements the Nikon 14-bit F0 stream format using
[LibRaw’s Nikon decoder](https://github.com/LibRaw/LibRaw/blob/master/src/decoders/decoders_dcraw.cpp)
as a format reference (LibRaw LLC and Dave Coffin).

Nikon has not sponsored, endorsed or supplied this project. Nikon and Z8
identify the interoperability target; their owners retain their rights.
No source license here grants rights to Nikon firmware or proprietary data.
Users provide their own compatible firmware.

The model is incomplete. Synthetic ROM, MCU, sensor and timing inputs are
experiments, not recovered factory data or physical specifications.
No updater, flashing tool or physical-camera access is included.
