# Z63 shared-device backport

Source: [RdWing/z63-qemu 5c3b47c](https://github.com/RdWing/z63-qemu/commit/5c3b47c6428310e923520d81df74eff86fe1451c),
including its pinned shared221 donor
[WonderLantern/zr-qemu 8a00ceda](https://github.com/WonderLantern/zr-qemu/commit/8a00ceda6a7111e5e08220f9cc3889f57fce9d0f).
Target: Z8 C3.11, QEMU 11.1.1, starting from `c24e334`.
The [source map](z63-source-map.json) identifies the actual donor and adapted
source fingerprints. It is not a native-feature acceptance list.

The two Z63 firmware versions, C2.00 and C2.01, share one emulator codebase.
This adaptation takes their cumulative implementation through patches 0067,
while preserving the Z8 board, firmware identities, synthetic fixtures,
register extensions and accepted F0 lossless output. It does not run either
Z63 firmware on the Z8 machine.

## Feature disposition

| Z63 change family | Z8 disposition | Acceptance boundary |
| --- | --- | --- |
| Shared221 capture, HE forward/inverse, RAW transport, capture pool, programmed clock, DSP boot, motion, main output and Wave5 | Included as source with explicit opt-in properties and dependencies. Original DSP microcode, physical ISP equations and R3D integration are excluded. | Synthetic host tests and actual board MMIO; native single HE/HE★ captures separately accepted. Movie recording remains open. |
| NV12 live-view JPEG and cancellation | Ported mode `0x32`, completed-generation tracking, overwrite invalidation, once-only consumption and pending-result guards. Existing NV16 remains covered. | Host codec/provenance tests; Z8 PTP/RTSP delivery remains unqualified. |
| JPEG decode and saved-preview resize | Ported both JPEG cores, per-core epochs, NV16 geometry/span/padding/overlap checks and output-before-IRQ ownership. | Production resize/rendering tests and one native saved-photo display accepted. Zoom and return-to-Photo recovery remain open. |
| Capture drains and movie exit | Ported source/processing ownership, deferred drains, masked-statistics reset and finite/continuous input separation. | Synthetic tests; repeated Z8 capture and movie return remain unqualified. |
| Task `0xff` status clear | Separate `task1500-ff-clear-model`, off by default. Z8's original zero clear is preserved. | Empty-status clear/arm/start controls; neither value creates task data. |
| Graphics/display | Preserve Z8 four-bank active acknowledgments, indexed overlays, region storage and additional rendering paths; add full-height NV16 direct scanout. | Actual renderer tests and original menu regression; physical panel/color fidelity unqualified. |
| Persistent virtual cards and exports | `--card` attaches an existing exFAT image for guest writes. Existing exact-file export plus bounded exFAT-window/ISO-BMFF helpers are available. | Guest-written lossless NEF accepted by two decoders. Export only after the emulator stops. |
| Photo/Movie selector | Browser control sends external MCU byte `0x57`, retained across every later button press/release. Input delivery and native mode acceptance stay distinct. | Browser popup/keyboard, queue, readback and shutdown checks. An explicit experimental profile now produces Movie frames and recovers to Photo; standard-profile and recording acceptance remain separate. |
| C2.01 NAND/startup/SNOR fixes | No target firmware, address, SNOR edit or provisioning recipe copied. Z8 keeps its existing boot and virtual store. | Original Z8 boot/menu/capture regression; no physical persistence claim. |
| STM32 reset/update/compare timers, IMU/I2C startup and native MCU controls | Optional native EX attachment now runs original Z8 MAIN/EX with Z8 GPIO/SPI glue; default capture/menu runs retain their host peer. | 73 synthetic reset/contact checks pass; original shooting display and Menu/navigation/half contacts reached. Remaining controls/capture remain open. |
| Z63 rotary dial, lens, top LCD, power and card-detect wiring | Z8 serial handshakes are mapped independently. The top-panel model is connected as a declared fixture; Z8 mode controls, lens/motor, power and card hot-plug still need their own bindings. | No physical or native Z8 qualification. |
| Go desktop UI, USB, plugins and board-specific diagnostics | The Z8 workbench now has a native macOS window with session lifecycle, screenshot saving and card-gated Playback. Native EX contact controls have separate acceptance from the host peer. Z63 assets/maps and USB/plugin routes are not copied as Z8 bindings. | Initial desktop integration is checked; complete debug/export/USB/plugin parity remains open. |
| QEMU host compatibility | Keep QEMU 11 core headers, console/loader APIs, architectural events, DesignWare ATU and all-vCPU breakpoint fixes. Build included C++17 HE sources with x264/x265/libjpeg. | Complete native macOS build; Linux full build remains untested here. |

## Preserve Z8 timed-single ownership

Z8's explicit `z8-timed-single-model` allows periodic input to own an armed
single request when source bitmap `0x201` is ready. It completes only after
the full D980 DMA, then publishes source/channel notifications once and
cancels the redundant timer. The imported finite/movie paths coexist with
that branch. A failed first integration lost this target behavior; the
corrected production-function test covers the missing-ready, refused-DMA,
periodic ownership, duplicate tick, reset and opt-out controls. The accepted
capture below uses the corrected implementation.

The F0 encoder remains enabled by default for the Z8 RAW transport. It
encodes the acknowledged guest-produced packed14 buffer with the original
four 2048 metadata seeds. Output length reports actual completed bytes.
No source-image substitution, injected camera file or physical codec claim
is made.

## Experimental shared profile

`tools/run.py --experimental-shared221` adds the explicit translated
configuration in `tools/experimental-shared221-profile.json`.
It excludes the ZR-only primary-bank property and the Z63 attachment's
independent boundary clock/lane acknowledgments. The existing Z8 controller
and boundary peer retain their own addresses. The profile is not the default
and is not a complete native Z8 workflow: Photo boot and input delivery can
advance without establishing sustained image production or movie recovery.

`--experimental-playback --card ...` enables the decode/resize model and its
prerequisites. It does not assert that every native saved-photo route has
been traced. Model properties remain available for bounded investigation;
passing a property dependency check is not camera acceptance.

## Validation on 20 October 2026

- Complete native QEMU 11.1.1 build on Apple Silicon, including the HE runtime
  and host AVC/HEVC dependencies.
- Host suite: 22 tests, 21 pass and one optional old-header comparison skips.
  Tests compile production ownership, timing, JPEG, HE and playback functions
  under ASan/UBSan. Existing region/serial/lossless and actual-renderer checks
  pass, including full-height NV16 versus half-height NV12 chroma rows.
- Actual board: 15 firmware-free MMIO checks pass, including video-domain
  commit/poll ownership, Wave5 identity/reset, three modeled DSP boot guards,
  task empty-status clearing and immutable source properties.
- Original Z8 C3.11 standard profile: 932 boot/menu checks pass, six native
  submenu/navigation/half-shutter inputs complete, 426 RAW frames and 969
  display frames observed, and the owned child stops cleanly.
- Fresh disposable-card lossless capture: 1,379 harness checks pass and the
  guest writes a 35,705,103-byte `DCIM/100NCZ_8/DSC_0001.NEF`. Its 34,946,319-byte
  F0 payload reflects the supplied 320×240/12-bit synthetic Bayer input
  expanded by the model to 8280×5520/14-bit. All 45,705,600 decoded samples
  match both the scaled input and the captured guest producer; LibRaw and
  Adobe DNG Converter agree with zero mismatches. All three previews decode.
  This is a fresh synthetic capture, not a physical photograph or repeated-shot test.
- Reopened persistent-card guest: 882 checks pass, native menus return, and read-only export of the retained NEF has the same SHA-256 as the fresh capture. Enabling the decoder does not qualify a playback workflow.
- Browser: native selector popup and keyboard selection, queued Movie input,
  a later half-shutter preserving Movie, and owned shutdown/disabled controls
  checked. The standard Movie attempt reaches unsupported access after a
  native diagnostic, while the explicit shared profile delivers controls
  without qualifying fresh movie frames. Neither is a successful Z8 movie test.
- Frontend static audit: zero errors or warnings. Narrow-viewport interaction
  and full native desktop parity were not exercised.

Reproduce the public source/model checks without Nikon inputs:

```sh
python tests/run.py
python -m unittest discover -s tests -p 'test_*.py' -v
python tests/check_shared221_mmio.py --qemu /path/to/qemu-system-aarch64 --output /tmp/z8-mmio-new
python tools/audit_source.py
```

Use [the existing capture recipe](capture.md) with explicit private inputs for
native acceptance. Firmware, cards, screenshots, NEFs, runtime captures and
compiled outputs remain outside the source inventory.

## Native Z8 parity follow-through

[Native HE stills](native-he-stills.md) now has original C3.11 single-capture
HE★/HE acceptance, full-strip inverse decoding, three preview decodes and a
regular-HE producer/receiver comparison. Finite HE STOP follows actual output
and original acknowledgements. Repeated capture and recovery remain separate.

`tools/run.py --replay sequence.json` replays ordered external controls against
virtual time after native menu readiness. It records delivery and preserves the
Photo/Movie selector through later buttons. `--trace-transitions` adds bounded
read-only exception observations; it changes neither instructions nor registers.
The controller now accepts the statically traced `play` input for saved-photo
experiments. Replay completion alone does not assert native workflow success.

The opt-in movie selector16/preparation and YUV readiness experiments remain
unqualified. They distinguish missing external table data, empty-channel
readiness and actual frame production. YUV ready state2 acknowledges arm state1
without DMA, queue results or interrupts. Saved-photo GPU mode8 is a functional
output-table-only interpretation requiring all three tables; physical stage
semantics remain unverified.

The [native EX attachment](native-mcu.md) now reaches the original shooting
display and has firmware-free reset isolation coverage. The optional
`--experimental-boundary-inputs` diagnostic supplies masked auxiliary-bank-1
and global-bank-0 bit 26 at 33 ms virtual intervals without catch-up bursts.
Those additional inputs did not restore movie or saved-photo return frames.
An unused bank-1 start-acknowledgement hypothesis was removed rather than
retained as a successful recovery model.

The [macOS workbench](../desktop/README.md) now shares the browser's controller
queue and readiness/capability guards. A native desktop run opens the retained
NEF through the original playback path and saves exact display pixels; closing
the window reaps its child. Native EX mode optionally enables qualified Menu/navigation/half contacts;
other controls retain capability guards.

A separate `--experimental-independent-pixel-clock` control disables the donor
capture-tick pacing while retaining the baseline periodic pixel clock. It
records admission masks `0x800e00` / `0x800e80` after the Movie/Photo replay,
with zero RAW/video frames. Header, ISP, source-gate and source-clock readiness
remain absent. This control does not fix movie pixels or establish recovery.

## Movie live view and recovery checkpoint

The explicit shared profile now admits the original 1920×1080 video header
bank at `0xE000E100`, only with pitch 5,888 and matching paired headers,
geometry, buffer ownership and pending-cause checks. The global task pulse
model retains the original one-to-zero enable edges without producing DMA or
completion interrupts. Empty YUV channels acknowledge arm 1 as ready 2 only.
The missing external selector16 record remains a declared synthetic input.

`--experimental-sensor-source-clock` requires the shared profile and keeps the
Z8 sensor VD owner distinct from capture group 0. When group 0 stops while the
programmed sensor clock is still running, that existing VD callback advances
source boundaries and owed frame work. It creates no independent oscillator,
CPU redirection or firmware RAM repair. Donor frame-done ownership remains on.
Firmware-free tests exercise the actual callback and disabled, stopped-clock,
bad-control, bad-period and active-capture guards.

Two cold-boot runs produced 1,089 and 1,129 functional movie frames and renewed
Photo, Menu and half-shutter frames after both returns in each run, with zero rejected
frames and clean shutdown. Use `--experimental-shared221`,
`--experimental-boundary-inputs`, `--experimental-yuv-channels`,
`--experimental-movie-selector16` and `--experimental-sensor-source-clock`
together with `--replay tools/movie-recovery-replay.json`; omit the still-preparation override and independent-pixel-clock
negative control. Movie input is functional 4,140×2,344 Bayer with a simplified
1920×1080 ISP output. A 2160p30 UI label does not establish 4K recording.
No movie container, audio, physical cadence or original-EX movie workflow is
qualified. Saved-photo playback still fails to resume Photo pixels. Posting
A1 finite-input-end bit 16 after actual reads/writes did not fix that lifecycle
and is excluded from the accepted model.
