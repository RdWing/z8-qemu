# Testing

```sh
python tests/run.py
python tools/audit_source.py
```

The source suite checks Python syntax, CLI entry points, local imports,
synthetic ROM generation and sparse-card copying. It compiles the region,
serial, timed-single and lossless-encoding contracts with strict warnings and tests the actual
display scanout and overlay functions against bounded mock RAM with address
and undefined-behavior sanitizers.

Lossless checks cover a fixed known bitstream, every signed difference category,
Bayer predictor parity, padded input rows, unchanged inputs and output-capacity
rejection under address and undefined-behavior sanitizers. The audit regression
rejects the former 80,017,920-byte packed payload under the compressed RAW tag.

Renderer checks cover four framebuffer banks, valid-fetch active latching,
rejected addresses, region positioning and clipping, palette banks, partial
alpha, transparency and invalid DMA or stride rejection.

A complete macOS QEMU 11.1.1 build, native boot and menu navigation, and
single NEF capture have passed with fresh synthetic sensor and card inputs.
LibRaw and Adobe DNG Converter independently decoded all 45,705,600 RAW samples
with zero mismatches against the sensor input and guest producer buffer. All
three JPEG previews also decoded. LibRaw’s packed-size fallback is explicitly
excluded before accepting the Nikon lossless payload. The
read-only card audit passed. Source integration is repeatable. Linux runtime
qualification, repeated shooting and post-shot recovery remain separate work.

For runtime acceptance, record firmware, binary and input hashes. Check
preparation callbacks, ready notification, shutter consumption, full-frame
DMA, single completion, capture drain, initialized card files, independent
RAW and preview decoding, and process shutdown. Repeated or burst operation
and post-shot recovery require additional validation.

`source-manifest.json` records the source inventory and fingerprints.
`tools/audit_source.py` detects mismatches and unexpected files outside `.git`,
`.local`, Python cache directories and macOS `.DS_Store` metadata. Refresh the manifest when intentionally
editing source. Keep runtime inputs and outputs outside tracked files.
