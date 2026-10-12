# Testing

```sh
python tests/run.py
python tools/audit_source.py
```

The source suite checks Python syntax, CLI entry points, local imports,
synthetic ROM generation and sparse-card copying. It compiles the region,
serial and timed-single contracts with strict warnings and tests the actual
display scanout and overlay functions against bounded mock RAM with address
and undefined-behavior sanitizers.

Renderer checks cover four framebuffer banks, valid-fetch active latching,
rejected addresses, region positioning and clipping, palette banks, partial
alpha, transparency and invalid DMA or stride rejection.

A complete macOS QEMU 11.1.1 build, native boot and menu navigation, and
single NEF capture have passed with fresh synthetic sensor and card inputs.
Independent decoding checked all 45,705,600 RAW samples against the sensor
input and guest producer buffer, and decoded all three JPEG previews. The
read-only card audit passed. Source integration is repeatable. Linux runtime
qualification, repeated shooting and post-shot recovery remain separate work.

For runtime acceptance, record firmware, binary and input hashes. Check
preparation callbacks, ready notification, shutter consumption, full-frame
DMA, single completion, capture drain, initialized card files, independent
RAW and preview decoding, and process shutdown. Repeated or burst operation
and post-shot recovery require additional validation.

`source-manifest.json` records the source inventory and fingerprints.
`tools/audit_source.py` detects mismatches and unexpected files outside `.git`,
`.local` and Python cache directories. Refresh the manifest when intentionally
editing source. Keep runtime inputs and outputs outside tracked files.
