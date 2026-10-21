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
| JPEG decode and saved-preview resize | Ported both JPEG cores, per-core epochs, NV16 geometry/span/padding/overlap checks and output-before-IRQ ownership. | Production resize/rendering tests and one native saved-photo display accepted. Normal two-cycle Photo/Menu return is accepted; zoom and idle-wake remain open. |
| Capture drains and movie exit | Ported source/processing ownership, deferred drains, masked-statistics reset and finite/continuous input separation. | Synthetic tests; explicit Movie/Photo recovery qualified below. Three consecutive original-EX HE★ captures pass; repeated host-peer lossless capture remains open. |
| Task `0xff` status clear | Separate `task1500-ff-clear-model`, off by default. Z8's original zero clear is preserved. | Empty-status clear/arm/start controls; neither value creates task data. |
| Graphics/display | Preserve Z8 four-bank active acknowledgments, indexed overlays, region storage and additional rendering paths; add full-height NV16 direct scanout. | Actual renderer tests and original menu regression; physical panel/color fidelity unqualified. |
| Persistent virtual cards and exports | `--card` attaches an existing exFAT image for guest writes. Native stopped-card batch export and exact-file export plus bounded exFAT-window/ISO-BMFF helpers are available. | Guest-written lossless NEF accepted by two decoders. Export only after the emulator stops. |
| Photo/Movie selector | Browser control sends external MCU byte `0x57`, retained across every later button press/release. Input delivery and native mode acceptance stay distinct. | Browser popup/keyboard, queue, readback and shutdown checks. An explicit experimental profile now produces Movie frames and recovers to Photo; standard-profile and recording acceptance remain separate. |
| C2.01 NAND/startup/SNOR fixes | No target firmware, address, SNOR edit or provisioning recipe copied. Z8 keeps its existing boot and virtual store. | Original Z8 boot/menu/capture regression; no physical persistence claim. |
| STM32 reset/update/compare timers, IMU/I2C startup and native MCU controls | Optional native EX attachment now runs original Z8 MAIN/EX with Z8 GPIO/SPI glue; default capture/menu runs retain their host peer. | 77 synthetic reset/contact/read-only checks pass; original shooting display, Menu/navigation/half, Movie/Photo and card-backed Play/early return reached. Original-EX HE files now have separate source/decoder acceptance; three consecutive HE★ captures recover normally with explicit sync wiring; remaining controls stay open. |
| Z63 rotary dial, lens, top LCD, power and card-detect wiring | Z8 serial handshakes are mapped independently. The top-panel model is connected as a declared fixture; Z8 lens/motor, power and card hot-plug still need their own bindings; the native Photo/Movie lever now has separate acceptance. | No physical or native Z8 qualification. |
| Go desktop UI, USB, plugins and board-specific diagnostics | The Z8 workbench now has a native macOS window with session lifecycle, screenshot saving and card-gated Playback. Native EX contact controls have separate acceptance from the host peer. Z63 assets/maps and USB/plugin routes are not copied as Z8 bindings. | Initial desktop integration is checked; session-log and photo export dialogs are native and checked; debug/USB/plugin parity remain open. |
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

FRONT preparation and source START have separate timing. A pending request
now waits for the unchanged bitmap `0x201` before spending its 64 admitted
DMA attempts. A production-function regression holds it through 96 waiting
polls, then checks one completed frame and the existing refusal/stop/reset
controls. The original-EX [HE diagnostic](native-he-stills.md#original-ex-source-start-timing)
produces and audits guest-written HE★ and HE files. Explicit original-EX sync
wiring closes the subsequent GPIO timeout and accepts three consecutive
HE★ captures without a reset-error screen. The periodic host-peer path retains
its original admission gate.

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

The earlier selector16/preparation and YUV readiness experiments alone did not
qualify Movie. The later complete live-view recipe below has separate acceptance. They distinguish missing external table data, empty-channel
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
qualified. The earlier delayed saved-photo exit did not resume Photo pixels. Posting
A1 finite-input-end bit 16 after actual reads/writes did not fix that lifecycle
and is excluded from the accepted model.

The macOS workbench also exercised this explicit Movie profile: selector inputs
at 42.61/68.05 virtual seconds entered Movie then Photo; Menu at 99.04 and half
at 138.88 reached their original displays. It produced 667 movie frames and
2,366 total RAW frames by 161.5 virtual seconds, then closed without a guest
error and reaped its owned child.

## Finite playback ordering

The saved-preview transfer now executes at A1 START using a retained,
epoch-checked decoded input and validated F4/B4 geometry. Both output planes
precede input first/data/end and B4 writer notifications. Enabled source-14
luma statistics consume the same actual input and expose 256 saturating
24-bit bins before the E event. Original W1C owns every cause. A B6 pulse
produces control only: source inspection places it in timeout cleanup, after
the finite initializer has already awaited input and histogram data.

Two cold-boot controls display the retained NEF with successful original
input/histogram waits and initializer return, one 1,396,736-byte resize each.
This corrects the earlier display-after-timeout ordering. A separate final
source run completes two Play/half/Menu/half cycles: two 1,396,736-byte resize
jobs, with fresh Photo RAW counts 435 after the first return, 786 after the
second and 960 after its final Menu/half. Exit occurs six virtual seconds after
Play input. Use `--replay tools/playback-recovery-replay.json` with the explicit
shared/boundary/playback/card/sensor-source-clock recipe. Idle-wake and zoom
remain open: in the delayed control, MAIN left playback for mode 0 before
right/half inputs arrived, accompanied by MCU mode request 9. Transport
completion alone did not wake that state.
Production tests cover immutable input, padding, decoder epochs, pending
owners, cancellation and absence of pixel work from the timeout pulse.


## Original EX Movie and card controls checkpoint

The original controller now supplies Movie/Photo reports from the verified
expander `0x23` bit 10, and Play from bit 5. Native Movie capabilities require
the complete five-option live-view recipe; Play requires an attached exFAT
card, playback model, shared profile, boundary inputs and sensor source clock.
Both server admission and shared browser/desktop configuration enforce these
gates. Native EX owns replies; card attachment keeps host controller-GPIO
replies disabled. No Z63 physical button names are inferred for unknown pins.

Separate cold-boot contact and interactive workbench runs produced 97 and 261
Movie frames with matching ISP/source acknowledgments, then recovered through
Photo/Menu/half. Native card review independently completed two finite resize
jobs, with normal early Photo/Menu/half return and fresh RAW frames. The later
review idle transition reaches original firmware terminal power-down and still
fails the tested half/Menu wake sequence. See
[native MCU evidence and replay](native-mcu.md#native-movie-and-card-workflows).

B6 timeout cleanup now retains only its control pulse, independent of a past
playback epoch or geometry. It performs no DMA and creates no completion.
Actual output remains exclusively guarded at A1 START. Production-function
ASan/UBSan tests preserve invalid-pulse rejection, pending-owner checks and
pixel/epoch admission. The updated host suite passes 41 of 42 tests with one
optional legacy comparison skipped; all 18 board MMIO checks and the strict
frontend audit pass. The macOS bundle builds and its signature verifies.
Encoded recording, continuous shooting, idle wake/zoom and full desktop
integration remain open; the later original-EX HE checkpoint below separately
qualifies three consecutive captures. This PR remains a bounded backport.


## Desktop commands and terminal power-down checkpoint

Native AppKit Camera commands now use the same guarded selector as the browser
popup, with proper menu validation and origin-checked readiness. An original-EX
window completes Movie→Photo→Menu→half with 135 Movie frames, matching ISP/source
acknowledgments and 870 RAW frames. There are zero checksum/pixel errors and
window close stops the owned session. The popup automation limit is separate.

Read-only CPU/GPIO observations distinguish terminal firmware power-down from
an ordinary playback wait. The backend detects the verified C3.11 three-core
SRAM park, disables controls and cancels pending inputs while retaining the last
frame. Original-firmware readiness changes from true to false at 33.2 virtual
seconds in a clean test. All 77 MCU reset/contact/read-only checks pass.

Desktop input checks now run off the UI thread, with exact-file access recovery
and startup cancellation. Session restart waits for the owned launcher to exit
before opening the same card in a fresh cold session. Native checks now cover
Stop during a pending file check, access-picker Cancel, a manual exact-input
grant that resumes startup, early boot Stop, and two cold restarts. After terminal power-down at virtual
28.784, the original session stops cleanly; the next session reopens the same
NEF and returns to fresh Photo frames (419 RAW frames). Each review completes
one finite resize job, with no checksum failures. Picker cancellation now
reports startup cancellation instead of a misleading file-save error. Physical wake/reset/fastboot, remaining
MCU
contacts and complete desktop parity remain open.


Native Session → Save session log now copies the stopped launcher's single log
through a Save dialog, retaining the source. A 103-byte export matches exactly;
active-session disable, stopped-session enable and dialog cancellation are
checked. Card/NEF export and the remaining debug/USB/plugin routes are separate.


## Original-EX date gate and Photo stop routing

A stock date-editor commit clears the original MAIN date permission reason;
the next release selects sequence 3 and submits D980 configuration. The Photo
stop classifier retains the existing direct route under shared Movie models.
Neither correction creates pixels or bypasses SfltDriver admission.

The [finite original-EX input](native-he-stills.md#original-ex-source-start-timing)
now follows the original SIF source START rather than waiting for the later
preview bitmap. Its generation, descriptor, reset and video-owner checks guard
one actual frame before notification. A source-only public replay saves and
audits HE★ or ordinary HE with original MAIN/EX and declared synthetic inputs.
Both processing banks retain fresh-source and original W1C ownership. The
explicit native HE profile also routes capture sync through actual EX GPIO
input/output. Baseline and accelerated single captures return to Photo, and a
three-release replay writes three independently audited HE★ files without a
reset action or error display. Ordinary HE is separately audited. Host tests
cover delayed admission, finite start generations, original-output-only wire
completion and bounded per-capture snapshots. Shared browser and native Camera
controls expose the guarded paired-contact action; physical exposure/wiring,
encoded Movie recording, idle wake and wider desktop parity
remain open.


## Native HE desktop checkpoint

At baseline instruction timing, early-startup Stop and same-card cold Restart
complete before the stock HE setup. Camera-menu, C-shortcut and browser-button
captures then write three consecutive, independently audited HE★ NEFs. Capture
and mode commands are disabled while busy, with Stop available. Newly written
`DSC_0003.NEF` opens in original playback, completing one 1,396,736-byte review
job. Half-shutter returns to Photo UI mode 6; the last preview is retained, so
fresh continuous Photo pixels are not qualified by this HE-profile check.
The run passes 372 checks with 1,935 MAIN / 1,855 EX frames, no checksum failures
and clean owned shutdown. The readiness guard uses the observed shooting mode
6 and rejects menu/review modes 1/2, preparation, pending output and the
sixteen-snapshot bound. Source tests cover those admission cases.

At this HE checkpoint: 46 host tests (45 pass, one optional legacy comparison skipped),
18 board MMIO checks, 77 MCU checks, production renderer/source closure,
217-file inventory and strict frontend audit. The signed macOS app builds.
These checks do not close the remaining parity gates listed above.


A combined accelerated control retains the explicit HE preparation while
switching to Movie, Photo and playback after one capture. The Movie screen
appears, but continuous RAW and Movie-frame counts remain zero. Playback still
completes one 1,396,736-byte job and half returns to Photo UI; the HE file passes
its own full audits. The run passes 388 transport/runtime checks with
2,327 MAIN / 2,192 EX frames, zero checksum failures and clean shutdown, but
those checks do not qualify combined Movie pixels. HE capture sessions now
disable browser/native Photo/Movie commands; the separately qualified Movie
session profile retains them. Host HTTP and actual JavaScript tests verify
that Capture remains enabled independently of disabled mode selection.


## Native photo-export checkpoint

The macOS Session menu exports initialized DCIM NEF/JPG/JPEG files from a
stopped matching virtual-card session into a new folder. It uses explicit
QEMU file locks, an independent reader worker, bounded extraction and atomic
no-replace publication. Cancellation reaps the worker and removes its private
staging directory. No firmware or card is bundled. See the [desktop operation
and acceptance limits](../desktop/README.md#export-photos-from-a-stopped-card).

Three actual native-dialog exports match the previously audited guest NEFs
byte for byte; this does not extend their codec or physical-camera acceptance.
The host suite now runs 52 tests (51 pass, one optional comparison skips).
Four actual-QEMU lock checks exclude existing/new writers, allow reopening after
release and preserve the card. Native startup diagnostics retain a separate
macOS initializer wait at the repository path; relocating the identical binary
starts original MAIN/EX and cold restart. The underlying host cause is unresolved.
