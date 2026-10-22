# Testing

```sh
python tests/run.py
python tools/audit_source.py
python tools/audit_privacy.py --history
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

The [Z63 backport validation](z63-backport.md#validation-on-20-october-2026)
separates host contracts, actual-board MMIO and original Z8 guest acceptance.
The production timed-single test supersedes the older copied C timing model.
Run the complete host suite with `python -m unittest discover -s tests -p 'test_*.py' -v`.

Privacy tests check redacted pattern findings, removed historical content,
historical payload names, and manifest-only runtime packaging. The packager
excludes unlisted files, verifies source hashes before copying, and rejects
symlinks, path traversal and non-source payloads. These controls supplement
manual review of documentation, PR text, logs and published artifacts; they do
not guarantee that every private fact matches a pattern. History checking needs
a full clone; the source CI job fetches complete history for that check.

The optional [read-only tracing plugin](../plugins/README.md) has a separate
firmware-free runtime check against the actual QEMU plugin ABI:

```sh
python3 tests/check_trace_plugin.py --qemu /path/to/qemu-system-aarch64 \
  --plugin /path/to/libz8trace.dylib --output .local/new-trace-check
```

Its 48 checks cover synthetic A53/M4 execution, argument/store values, filtering,
bounds and rejected configurations. Host tests validate launcher profiles; source
CI does not load an external plugin binary. Native macOS checks separately cover
trace selection, restart, stopped-log retention and the unconfigured disabled state.

`tests/check_mcu_adc.py` separately executes synthetic M4 ADC conversions on the
actual board. Diagnostic ZIP host tests cover exact binary log copies, fixed
allowlist exclusion, limits, nonregular inputs, source changes, cancellation and
no-replace publication. Native Save-dialog/completion checks remain separate.

`tests/check_mcu_panel.py` executes synthetic PA1/EXTI1 and SPI2 transfers through
the actual board. Its 13 checks distinguish Z8's 144×168 geometry from the
reference model, including gates 1/168 and the eighteenth data byte, with
partial/invalid/unselected negatives. Host PNG/HTTP and production-JavaScript
checks cover display blanking, bounds, capability, image versions and retained
pixels on disconnection. Original EX drawing and native UI remain separate
runtime acceptance.
