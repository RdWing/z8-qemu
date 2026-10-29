# Original Z8 EX controller

The optional `mcu-image` attachment runs the user-supplied original Z8 EX03.00
alongside C3.11 MAIN. The existing host-peer launcher remains the capture/menu
baseline. This attachment uses no host MCU replies or firmware instruction
patches. It is experimental; contacts and bounded workflows are qualified separately below.

```sh
python tools/run_native.py --firmware /private/MAIN.bi --mcu /private/EX.bi \
  --qemu /path/to/qemu-system-aarch64 --raw /private/synthetic.raw \
  --output /private/new-native-run --seconds 180
```

The launcher checks both firmware identities and keeps outputs outside the
source inventory. It clocks declared external boundary/SPI inputs and records
read-only native state, frames, initialized MCU data and CPU observations.
`--mcu-pins G1=1:G13=1` supplies explicit GPIO contacts for investigation;
this is not an inherited Z6III button map. `native-mcu-wire-state` exposes the
last complete frame per serial channel/direction. No register/PC redirection
or firmware RAM repair is performed.

## Native result

A 180-second host run reached the original shooting display, with 263 functional
RAW frames and 234 display frames by 19.84 seconds of virtual time. The final
display had original overlays over a black image area. The two original
components exchanged 450 MAIN and 421 MCU non-idle frames with zero checksum
failures. A short 30-second run had not yet reached the display; wall time and
virtual firmware time must be distinguished.

The MCU's own code owns serial messages. Z8 PB14/PE3/PD12 feed MAIN port 3
bit 2 / port 3 bit 3 / port 4 bit 3; MAIN port 4 bit 7 drives PG6. SPI1 and
SPI4 connect to MAIN serial channels 0/1, converting each 16-bit MAIN word to
two low-byte-first eight-bit DMA items. GPIO polarity/mask/W1C state owns IRQs
57/58. The donor PB12 RX-ready binding is not used.

The compatible core/peripheral implementation derives from the pinned Z63
source. It uses QEMU 11 core timer/EXTI overlays with exact upstream/donor
fingerprints and divergence rejection during installation. The ordinary board
is still tested without a native MCU image.

## Declared inputs and open work

The compatible MCU clock is 180 MHz, timer clocks 90 MHz, RTC starts at
2026-01-02T03:04:05, and PD13 is a virtual battery-idle contact. ADC/I2C samples,
144×168 top-panel behavior and its ready delay remain functional fixtures. The
panel received one clear packet and zero line packets in the native run.
The donor mechanical shutter is unarmed and its position pins are not driven.
Exact physical chip identity/clock, remaining Z8 key/lens/power mappings, native
continuous shooting, encoded recording, physical wake wiring and top-panel timing
remain unqualified. Functional idle wake with the explicit supply fixture is
qualified below.
Movie live view, normal Photo recovery and card-backed review have separate
native acceptance below; the explicit HE profile also qualifies bounded full
capture and recovery.
No host-peer acceptance transfers to this attachment.

Firmware-free reset checks:

```sh
python tests/check_mcu_reset.py --qemu /path/to/qemu-system-aarch64 \
  --output /tmp/z8-reset-new
```

Clang with AArch64/Thumb targets is required. The script extracts relocation-free
ELF `.text` itself. All 77 checks pass across zero/one/two MCU resets: A53
heartbeat isolation, SRAM/flash/RTC backup retention, ordinary peripheral/core
reset and AIRCR negative controls, plus contact isolation, release, atomic invalid-batch rejection, read-only GPIO/EXTI/serial state for every port A through K and absence of fabricated messages. This is model validation, not camera capture
qualification.

## Original EX controls

`--native-controls --port 0` enables Menu, arrows, OK, i, DISP and half-shutter in the
shared browser workbench. Each action changes an external active-low contact;
original EX creates the switch report and MAIN consumes it. No host switch
messages or firmware memory edits implement these actions. Playback additionally
requires a supplied card and the explicit playback model. Photo/Movie additionally
requires all five experimental Movie options below. Other buttons stay disabled.

| Input | External contact | Original switch-report byte |
| --- | --- | --- |
| Menu | expander `0x23`, bit 6 | `0x43` |
| Down | expander `0x23`, bit 13 | `0x25` |
| OK | expander `0x23`, bit 11 | `0x4A` |
| Left | expander `0x23`, bit 12 | `0x23` |
| Up | expander `0x23`, bit 15 | `0x24` |
| Right | expander `0x23`, bit 14 | `0x22` |
| i | expander `0x23`, bit 7 | `0x48` |
| DISP | expander `0x23`, bit 8 | `0x53` |
| Half-shutter | PG1 | `0x07` |
| Playback | expander `0x23`, bit 5 | `0x44` |
| Protect | expander `0x23`, bit 9 | `0x49` |
| Delete | expander `0x23`, bit 18 | `0x45` |
| Photo/Movie | expander `0x23`, bit 10; high/low | `0x57` |
| Movie Record/Stop (replay) | expander `0x22`, bit 12 | `0x09` |

Explicit idle inputs PG1/PG13/PG14/PG15 are high. Releasing PG14/PG15 clears
report fields `0x6F/0x70`; leaving them low kept Menu blocked in the earlier
experiment. Their physical switch names remain unqualified. The original
124-byte report and checksummed wire frame are observable through
`native-mcu-switch-state`. `mcu-contacts` accepts validated atomic batches such
as `23.6=0:23.13=1`; malformed batches change no contacts.

A finite contact replay reached original Menu and returned to synthetic Photo
pixels with half-shutter. By 40.36 virtual seconds it exchanged 920 MAIN and
863 EX frames with zero checksum failures. A separate macOS desktop session
sent actual half-shutter/Menu contacts, displayed original Menu and stopped
cleanly, with 1,413 MAIN / 1,301 EX frames and zero checksum failures. These
checks establish the stated contacts and workflows. They do not qualify full-shutter
capture. Later card and Movie checks are described below. `--contact-replay` accepts finite ordered external contacts for
investigation and excludes interactive controls in the same run.

The [desktop workbench](../desktop/README.md) enables these contacts with both
`mcu` and `native_controls: true` in its configuration. Display-only native
inspection remains available by omitting `native_controls`.

## Native Movie and card workflows

Enable `--experimental-shared221 --experimental-boundary-inputs
--experimental-sensor-source-clock --experimental-yuv-channels
--experimental-movie-selector16` together. These are declared functional models;
the selector fixture is not factory calibration. The native selector changes
expander `0x23` bit 10 and stays latched while other buttons press and release.
Original EX supplies the resulting switch report. Boundary inputs are explicit
in this launcher, matching the host-peer recipe.

A cold-boot contact replay produced 97 Movie frames with 97 ISP and source
acknowledgments, then returned through Photo, Menu and half-shutter to fresh
Photo frames. It finished with 1,420 total RAW frames, zero rejected transfers,
1,417 MAIN / 1,281 EX non-idle frames and zero checksum failures. An interactive
shared-workbench run separately produced 261 Movie frames with matching
acknowledgments and recovered to Photo. That UI run also sent one OK input
while in Movie; the finite replay isolates the lever transition. Neither run
uses host MCU replies. The 2160p UI label does not qualify encoded 4K recording.

For native review add `--card /private/card.raw --experimental-playback` plus
the shared profile, boundary inputs and sensor source clock. The supplied
exFAT virtual card retains guest writes. Native EX remains the controller
owner; attachment explicitly disables the host controller-GPIO reply model.
A contact replay completed two 1,396,736-byte review transfers, with an early
half-shutter return, Menu and a second half-shutter returning to fresh Photo
frames. A later review entered UI mode 0 after about ten seconds; subsequent
half/Menu contacts did not wake that unwired session. The explicit supply
fixture below has separate idle-wake acceptance; review-specific late-idle wake,
zoom and full native controller parity remain unqualified.
The explicit HE still profile has separate repeated-capture acceptance below.

Use `tools/native-movie-recovery-contacts.json` for the bounded Movie replay.
Contacts are scheduled in virtual firmware seconds; wall duration must allow
the run to reach the last action. Interactive native controls require
`--native-controls --port 0`; omit `--contact-replay` in that mode.


A further cold boot attached the card while executing the native Movie replay.
It produced 114 Movie frames with matching ISP/source acknowledgments, returned
through Photo/Menu/half and reached 619 RAW frames at 40.4 virtual seconds.
All eight scheduled Movie-recovery contacts were delivered, there were zero
pixel rejects or checksum failures, and shutdown was clean (796 MAIN / 715 EX
frames). The wall-time limit ended this run before its later scheduled Play
input; it qualifies Movie with the card attached, not a combined review cycle.


The rebuilt AppKit workbench independently completes native Play/half/Menu/half.
Play is sent at virtual 20.535, review enters at 21.539, half returns to Photo
at 23.667, Menu opens at 28.153 and final half returns at 31.190. RAW count
advances from 351 during review to 453 after the first return and 518 by
window close. One 1,396,736-byte review job completes, with 761 MAIN / 710 EX
frames, zero checksum failures, zero pixel rejects and clean owned shutdown.
The native Movie popup selection was not committed in this desktop test;
shared-browser Movie and finite replay acceptance do not imply that action.


The native Camera menu separately completes Movie/Photo/Menu/half: Movie input
at virtual 13.474, Photo at 25.555, Menu at 33.545 and half at 40.501. It
produces 135 Movie frames with 135 ISP/source acknowledgments, then advances
to 870 RAW frames. Serial totals are 1,047 MAIN / 937 EX, zero checksum failures,
zero pixel rejects and clean window-close cleanup. Camera commands and the
popup share one selector function; native commands stay disabled during boot
and respect the same in-flight, capability and stale-session checks. A second
clean Camera-menu cycle sends exactly Movie/Photo/Menu/half, producing 50 Movie
frames with matching ISP/source acknowledgments and 796 total RAW frames. Its
915 MAIN / 825 EX frames have no checksum or pixel errors and owned Quit stops
QEMU cleanly. The WK popup-only rerun remains an automation limit; no extra
confirmation key is needed by the selector.

`native-mcu-io-state` observes MAIN GPIO levels/mask/pending/polarity/enable,
MCU GPIO input/output modes, EXTI routing/edges and serial ownership without
reading status-clearing device registers. Reset/contact checks now include
repeatable paused observation and explicit GPIO levels across ports A through K (77 checks). A bounded
idle reproduction confirms PG1 reaches its input at 36.077 virtual seconds,
while serial totals remain 750 MAIN / 694 EX after idle. That establishes
delivery to the pin, not a recovered wake path or physical wiring.


## Terminal power-down and recovery

The later review-idle failure reaches the original MAIN shutdown callback,
then terminal SRAM WFI loops on all three MAIN cores. Ordinary half/Menu inputs
cannot restore that state. A paired MAIN half-GPIO edge also fails to resume it;
no physical wake/reset wiring is inferred from these negative controls.

Read-only `runtime-clock-state` includes each CPU PC; `native-mcu-io-state`
records MAIN GPIO, EX GPIO/EXTI and serial state without clearing status or
creating interrupts. The C3.11 detector requires UI mode 0 and all three halted
MAIN cores at their verified terminal park addresses. Boot or scheduler WFI
alone does not qualify. It never redirects a CPU or edits firmware RAM.

An original MAIN/EX run first becomes ready, then detects power-down at 33.2
virtual seconds. The loopback status becomes `powered_down: true` and
`ready: false`, preserves the last display and rejects further camera inputs.
It stops cleanly with 750 MAIN / 694 EX frames and zero checksum failures.
Host tests additionally cover queued-input cancellation and sticky terminal
state. The desktop adds a cold Session restart using a fresh output directory
and the same inputs/card. Native-window startup cancellation and two cold
restarts now pass, including card review after the original firmware's terminal
power-down. This does not close physical wake or fastboot parity.


## Full-release report mapping

Original Z8 EX independently confirms PG13 low while PG1 is held: byte 7
remains one and byte 8 becomes one in the original 124-byte switch report.
PG13 release clears byte 8; PG1 release clears byte 7. The bounded replay sends
half at virtual 16.030, PG13 at 18.021, release at 22.037 and half release at
23.033. It stops cleanly with 609 MAIN / 573 EX frames and zero checksum failures.
Use `tools/native-full-report-contacts.json` with the original-EX contact-replay
recipe. This validates a Z8 report binding independently of donor names.

A switch report alone does not qualify image capture or the separately
modeled MAIN half/full GPIO inputs. The desktop full-capture action therefore
requires the separately qualified experimental HE profile below.
Earlier PF2 controls produce no byte-8 report, including a four-second hold
with actual input delivery observed. Runtime inspection validates all 19 direct
input descriptors; PF2 resolves to port 0x40021400/mask 4, so the negative result
is not a source-ID translation error. Expander 0x22 bit 2 and bit 5 instead
produce report bytes 5 and 14. These numerical bindings assign no additional
physical button names. Native full capture remains separate from the accepted
host-peer HE/HE★ workflow.


A paired-input RAW-menu replay reaches the original MAIN full-contact callback,
admission-pass branch, commit and initial sequence dispatch. Capture current/
pending and screen-busy state are zero, ruling out a busy admission rejection
for this control. D980 submissions and finite-frame/RAW-output/HE jobs remain
zero. The run stops cleanly with 2,065 MAIN / 1,938 EX frames and no checksum
failures, without host MCU replies, PC redirection or firmware RAM repair.
This earlier control narrows the join beyond admission; it does not qualify native
HE capture or the physical connection between EX and MAIN release inputs.


A full-phase-only read-only trace further reaches the UI action with the full
key and clear inhibit/busy/filter checks. Its sequence-permission getter returns
zero, selecting initial sequence 1; the accepted host-peer capture returns one
and selects sequence 3. Only active reason 37 intersects the current mask; active reason 125 is masked.
The probe stops cleanly at virtual 71.270584 with 1,622 MAIN / 1,533 EX frames,
no checksum failures and no image-engine jobs. These are firmware gate
observations; no reason bit or firmware instruction is changed to force a shot.


## Stock date setup and capture permission

The declared MCU RTC calendar alone does not clear the original MAIN date
permission reason. The stock Setup → Time zone and date → Date and time
editor is independently checked: changing the day from 2 to 3 and confirming
changes DateTimeService status from 0 to 2 and clears reason 37. After return
to Photo, permission becomes one and the next paired release selects sequence
3, submits D980 configuration and requests one finite frame. Use
`tools/native-date-setup-contacts.json` with the original-EX contact replay
recipe and idle `G1=1:G13=1:G14=1:G15=1`. It starts from the fresh Photo-menu
state and fixed virtual 2026-01-02 calendar; it returns to Photo after the date
commit. This tests stock UI/EX behavior without injecting a controller reply.

Date setup establishes permission; image production has its own source contract.
The earlier finite request expired before source admission, then the enabled
Movie handler intercepted the following Photo `0x401e` stop. Current-generation
routing fixes that stop without creating DMA. The subsequent missing-source
SfltDriver rejection was preserved while tracing the actual input trigger.

The [original-EX HE workflow](native-he-stills.md#original-ex-source-start-timing)
now binds original SIF START to the armed finite input and writes actual sensor
bytes before completion. HE★ and ordinary HE guest files pass complete RAW,
producer/receiver and preview audits. A public stock-date/RAW/release replay
uses original EX contacts plus explicitly declared MAIN GPIO contacts, with no
host MCU reply, firmware-state patch or source-validity bypass. The native HE profile explicitly connects MAIN request bit 12 to EX PF4 and
actual EX PD7 output to MAIN response bit 7 through the original interrupt
mask/polarity/W1C contract. Original firmware reaches its completion callback
and returns to Photo without the former reset error. Three consecutive HE★
files and an independent ordinary HE file pass full audits. This establishes
bounded virtual recovery; physical wire identity and exposure timing remain
unqualified. Shared browser and native Camera-menu capture controls use the
same guarded contact queue. The separate [stopped-card photo export](../desktop/README.md#export-photos-from-a-stopped-card) now has native dialog and exact-copy acceptance.


## Native Camera commands and i-menu graphics

The AppKit Camera menu now exposes MENU, Half shutter, Playback and i menu
through the same contact queue and capability/readiness gates. The native
sequence displays the original Menu, i settings grid and retained file 3,
then returns to fresh Photo frames. This adds desktop access to the qualified
contacts without introducing a new Z8 physical map.

The i-menu drawing route uses the donor empty `E73/A8/E85/A8` path family,
previously restricted to ZR. Z8 now accepts that exact pair with resident
paint/program and matched-end ownership; nonempty inline geometry remains
unsupported. Sanitizer controls and a native regression preserve the existing
`5E5/A8/5EC/A8` family and later draw completion. See the [desktop checkpoint](z63-backport.md#native-command-and-signed-runtime-checkpoint).


## Separate EX USART output

Native sessions connect optional QEMU character backends `z8-ex-usart1` through
`z8-ex-usart6` to the existing controller USART1/2/3, UART4/5 and USART6 register
instances. Desktop/CLI native runs use separate output-only files; no incoming
bytes or physical console role is synthesized. Without a named backend the
instance remains unconnected. The 95 synthetic controller checks include exact
per-instance TX across zero, one and two resets, with independent A53 progress.
The native inspected boot emits a single NUL on USART1; no interactive EX
console is qualified. The [desktop diagnostics window](../desktop/README.md#live-diagnostics)
keeps these streams separate from MAIN UART TX, QEMU diagnostics and launcher
messages. Native Camera navigation uses the same existing EX contact map.

## Explicit ADC inputs

The inherited functional model has three ADC instances with 19 declared 12-bit
samples each. `--mcu-adc-inputs 1.1=2048:3.18=4095` supplies decimal
`ADC.CH=VALUE` batches at startup. ADC numbers are 1..3, channels 0..18 and
values 0..4095; unspecified samples retain the 2048 default. This is a numeric
external input, with no recovered voltage, dial position or battery meaning.
It requires a native MCU attachment.

At runtime, set machine property `mcu-adc-inputs` with the same syntax. The
whole batch validates before any sample changes; duplicates, malformed values
and out-of-range values are rejected. Changing a sample does not run a
conversion, change completion flags or create an IRQ. The guest's existing
software-started regular/injected conversions consume the next samples. Inputs
survive a controller-only reset. DMA and longer regular scan sequences remain
unmodeled. The read-only `native-mcu-adc-state` snapshot reports all samples,
status, DR and four JDR values directly, without clearing EOC through an MMIO read.

Finite contact replay also accepts `mcu-adc-inputs` actions with the same strict
validation. Desktop configuration uses the `mcu_adc_inputs` string. No named
Z63 mode-dial preset is transferred.

```sh
python3 tests/check_mcu_adc.py --qemu /path/to/qemu-system-aarch64 \
  --output .local/new-adc-check
```

All 19 actual-board checks pass with synthetic A53/M4 programs: three regular
conversions, injected channel order, runtime sample updates, read-only state,
eight atomic rejection controls, input retention through MCU reset and independent
A53 progress. These checks qualify model input plumbing, not a physical MCU pin map.

## Z8 top-panel binding

The original EX panel uses 144×168 one-bit pixels: 168 rows of 18 bytes,
not the donor's 128×128 geometry. PA4 supplies active-high SCS, PE8 DISP and
PD11 the start pulse. The Z8 ready descriptor is PA1; driving donor PD1 left
the actual interrupt input unchanged. The ready substitute still waits a
declared five virtual milliseconds after the start pulse. This is not a
measurement of physical panel power-up.

The model accepts complete SPI2 row packets, including gates 1 and 168, and
retains memory across DISP-off observation. Invalid gates, partial rows and
unselected bytes cannot replace pixels. `native-mcu-panel-state` exposes
dimensions, counters, display/chip-select and ready state; `mcu-toplcd-bits`
returns exactly 3024 bytes as hex, without status-clearing reads.

The shared browser/native workbench shows the EX control panel below the camera
controls for a native attachment. The PNG preserves model memory order; the view rotates it clockwise for
readable text, without asserting physical panel mounting. Display-off and disconnected states are explicit; the last
received frame remains inspectable. Host-peer sessions have no panel view.
The native launcher also saves `toplcd.png` and the original `toplcd-bits.hex`
after stopping. These remain private runtime outputs.

Run `tests/check_mcu_panel.py` with `--qemu` and a fresh `--output` directory
for thirteen firmware-free actual-board routing/packet checks. Those tests
qualify model integration, not panel electronics or physical-camera behavior.


## Additional display control and zoom boundary

Original EX serializes expander `0x23` bit 8 into report byte `0x53`; original
MAIN consumes its display-switch mask. A finite native run presses/releases
that contact at virtual 18.0/18.4 seconds and removes the shooting overlays.
Browser DISP, the D shortcut and AppKit Camera → DISP share the qualified
contact queue and its readiness/capture/shutdown gates. Host-peer and native
display-only sessions keep DISP disabled. Modified keyboard shortcuts do not
send camera input.

The same run enters card-backed review, then identifies a distinct A1 zoom
selector. The model now accepts only matched selector/data-word pairs and the
single checked crop of a just-produced zoom surface. A native replay completes
three actual jobs: normal review, full-size JPEG to 1040×696 and its 1024×682
crop, totaling 4,241,152 output bytes. Cropped input reads only active rows;
stale epochs, incomplete output, padding, crossed planes and recursive crops
remain rejected.

The next original request uses a separate 384×256 single-address B4 format,
which remains strict and unsupported. The replay stops cleanly at that boundary
with zero checksum failures; zoom-out and Photo return are not reached. Zoom
controls remain disabled. Neither a decoded JPEG nor the two completed image
stages qualifies the full zoom workflow or physical filtering.

## External CFexpress detect input

With the existing explicit PCIe/card profile, QOM property
`cfexpress-card-present` can change the external port-2 detect sample at runtime.
It defaults to true; false clears only bit 1 of the original Z8 status query at
`0x17a00044`. `pcie-dbi-model` is required for mutation. This is a MAIN-side
input, independent of EX key contacts.

The NVMe endpoint, backing-file lock, PCIe wrapper, DMA state and other port
samples stay attached and unchanged. Original firmware must poll and own its
removal/insertion handling; the input creates no IRQ, transfer completion or
filesystem event. It does not simulate physical hot-unplug or make copying an
active card safe. Stopped-card export keeps its existing gate.

Twenty-four firmware-free actual-board checks cover present/absent boot,
repeated removal/reinsertion, unchanged endpoint/backing-file/adapter ownership,
neighbor isolation, read-only observation and rejection without the adapter.
A disposable-card original MAIN/EX run toggles false/true at virtual 19/23 seconds, then completes review and returns to Photo: 300 harness checks, 633 RAW frames, 761 MAIN/698 EX frames, zero checksum failures and clean shutdown. The backend stays identical. No absent-period filesystem event was independently observed, so complete native hot-plug remains unqualified.


## Native Protect and Delete keys

Z8 expander `0x23` bit 9 produces EX report byte `0x49` (Protect); bit 18
produces byte `0x45` (Delete). Original MAIN consumes distinct switch masks.
These target bindings are independent of the donor's key map.

On a disposable three-photo card copy, a finite original MAIN/EX replay enters
Playback, presses Protect twice, opens the native Delete confirmation and
confirms with a second Delete press. The screen shows the protection icon,
then the confirmation, then `DSC_0002.NEF` as `2/2`. A stopped-card catalog
independently confirms `DSC_0003.NEF` is absent and the two other NEFs remain;
the original card still has all three. Play returns to Photo and RAW frames
advance to 332. All 300 harness checks pass, with 682 MAIN / 641 EX frames,
zero checksum failures and clean owned shutdown at 30.003 virtual seconds.
This is a bounded emulator workflow, not physical control qualification.

Browser Protect key / Delete key and the matching AppKit Camera commands use
the existing per-button admission, queue and contact release. Both require
native EX controls plus a virtual card and playback model; host-peer,
display-only, stale and capture-busy sessions reject them. Neither has a
keyboard shortcut. Watch the camera's own confirmation: another Delete press
can remove the selected virtual-card file. The queue reports input delivery,
not a saved protection flag or completed deletion. Confirmation cancellation,
protection persistence after restart and other assigned shooting roles remain
separate checks.


## Native Main/Sub command dials

The original Z8 EX pin table and polling routines independently bind Main to
PE7/PE13 and Sub to PF11/PF14. Each external pair follows a complete four-phase
Gray cycle; original EX emits the signed report delta. The workbench's Main/Sub
minus and plus buttons and AppKit Camera commands reuse the existing queue.
They require native EX controls, with no added card requirement. Host-peer and
display-only sessions keep them disabled.

One queued turn produces a single `-1` or `+1` EX count, rather than a host
switch packet or firmware memory write. Each phase lasts at least 80 virtual
milliseconds; this is a declared input cadence, not measured dial electronics.
Late ticks do not collapse phases. Turns serialize with buttons/modes/capture;
Stop releases an unfinished turn to its starting levels and never retries it.
Signs name the firmware delta, without claiming clockwise physical rotation.

A finite original MAIN/EX run records all four signed report pulses, navigates
menu entries and enters/leaves a submenu. It also accepts a Main-plus turn from
the live browser. Half-shutter returns to Photo, with 269 RAW frames at virtual
28.029, 635 MAIN / 602 EX frames, zero checksum failures, all 300 harness checks
passing and clean owned shutdown. The pulses last about eleven virtual
milliseconds; ordinary half-second host snapshots missed some of them, so the
acceptance uses separate read-only higher-frequency report observations.

Browser 640px layout, live queue feedback and disconnected disabling are checked.
The native menu bridge has host checks and a signed macOS build. ISO chords, lens-dependent settings, rapid continuous turns and
physical dial timing remain separate work.

### Exposure-mode chord

Exposure mode minus/plus holds the independently qualified MODE contact
(expander `0x22`, bit 5) around one Main dial turn. Original EX supplies MODE
at report byte `0x0E` and the signed Main count at `0x0B`; the host neither
writes a setting nor constructs a switch packet. Each finite chord settles
for 250 virtual milliseconds before turning and holds for another 250 after
its last phase, then releases. Stop cancels either phase and releases MODE;
later inputs wait for the entire chord and its cooldown.

The shared browser and Camera-menu commands use the existing dial capability,
readiness, bounded queue and capture guard. No modifier toggle or keyboard
shortcut is introduced. The original-firmware no-electronic-lens fixture
advances through the mode selection and retains M after release. P/S selection
highlights can return to A in the shooting display; this is not evidence of
a lost dial count. The exact lens/effective-setting gate remains untraced,
and lens-supported P/S exposure is not qualified.

The finite production run passes all 281 harness checks, with 724 MAIN / 674
EX frames, zero checksum failures and clean shutdown at 31.035 virtual seconds.
It returns from M to A, then accepts a live browser mode-plus input and retains
M again. The host suite runs 89 tests (88 pass, one optional skip); source and
renderer contracts, strict UI audit, signed macOS build and signature checks
pass. Exact shutter-step consumption, restart persistence and new AppKit-menu
runtime clicks remain separate acceptance gates.

### Exposure-compensation chord

Exposure compensation minus/plus holds the target compensation contact
(expander `0x22`, bit 3) around one Main turn. Original EX supplies the button
at report byte `0x15` and the signed Main count at `0x0B`. The shared finite
modifier owner handles MODE and compensation: 250 virtual milliseconds to
settle, four separated dial phases, another 250 milliseconds held, then release
and cooldown. Stop restores both inputs; later actions cannot interleave.

An original MAIN/EX contact replay displays `0.0 → +0.3 → +0.7 → +0.3` for two
positive counts and one negative count. This is the firmware's displayed
third-EV step in the tested fixture. The host never writes an EV value, and
the firmware owns custom step/reversal behavior. Metering, physical exposure,
saved-pixel changes, limits and restart persistence remain separate gates.

The production HTTP queue separately displays `0.0 → +0.3 → +0.7 → +0.3 → 0.0`;
a live browser plus request displays `+0.3` again. Original EX reports every
hold, count and release. All 208 harness checks pass with 695 MAIN / 652 EX
frames, zero bad frames and clean stop at 30.054 virtual seconds. The browser's
640px layout and disconnected disabling are checked. Host tests pass 88 with
one optional skip; source/renderer contracts, strict UI audit and signed macOS
build/signature checks pass. New AppKit menu clicks retain separate runtime
acceptance; the shared bridge/build checks do not qualify them.

## Native main-switch shutdown input

Target EX input tables and original MAIN/EX execution now bind the main-switch
sense to PC5. Low is the running sense in the tested fixture. Replaying
`mcu-pins` value `C5=1` changes original report byte 4 from 1 to 0 and invokes
software shutdown; MAIN reaches its terminal SRAM WFI loops. This uses the
existing explicit contact-replay interface, with no firmware memory/PC writes
or host switch replies.

The finite check passes all 210 harness checks, with 429 MAIN / 396 EX frames,
zero bad frames and clean owned shutdown. Before STOP clock gating, returning PC5 low does not resume
MAIN, and the candidate wake pulse leaves the retained byte off. The STOP and
explicit supply-fixture results below supersede that modeled limitation;
physical power/reset wiring remains under investigation. Unwired sessions use
the separately qualified cold Session restart. The explicit C1 fixture exposes
a bounded Wake camera action below; it does not infer an electrical reset wire.
Physical wake, fastboot and full retained-memory behavior remain unqualified.

## RTC alarm and wake events

The RTC model now generates Alarm A/B and periodic wake flags from the declared
32768 Hz LSE input. Calendar field masks and subsecond comparisons select alarm
matches; WUTR and WUCKSEL select the wake interval. Enabled flags drive EXTI17
(shared Alarm A/B, NVIC41) and EXTI22 (wake, NVIC3). Delivery still requires the
guest's EXTI edge, mask and NVIC configuration. Clearing a flag lowers its RTC
source even while WPR is locked; INIT and configuration remain protected.
Disabling a timer cancels future events. MCU-only reset retains the
backup-domain calendar, controls and active timer, while resetting EXTI/NVIC.
The read-only `native-mcu-io-state` RTC fields expose stored flags, configuration,
match/expiry counters and source levels without acknowledging an event.

Sixteen firmware-free actual-board checks cover periodic timing, pending-flag
interrupt enable, locked-handler flag clearing, masked/unmasked EXTI delivery, repeated alarms, calendar/date
and weekday matches across a year boundary, flag clearing, timer cancellation,
MCU-reset retention and independent A53 progress. The test uses an explicit
instruction-count clock so host scheduling does not determine its timing check.

Original MAIN/EX enables Alarm A while running and a wake timer after shutdown.
The new model produces 20 Alarm A matches and 74 wake expiries by 36.045 virtual
seconds in the finite replay; its 210 harness checks pass with a clean stop.
The strengthened locked-handler fixture rejects the previous binary after its
first wake interrupt and passes on the corrected build. Original EX now clears
repeated Alarm A flags, with 422 MAIN / 409 EX frames and zero bad frames.
In this earlier RTC-only run, MAIN remains in terminal SRAM wait loops.
After shutdown, EX has the wake interrupt and EXTI mask enabled but the
sampled rising/falling edge selections are clear. A read-only store trace
confirms earlier rising-edge configuration followed by later GPIO configuration
writes. Generating RTC flags alone does not qualify native wake or restart.

Calendar time retains the existing one-virtual-second fixture; arbitrary
prescaler/oscillator accuracy, non-LSE clocks, calibration, timestamp/tamper,
backup-domain reset and physical wake wiring remain separate gaps. The model
does not infer a board reset wire or force firmware to resume.

## STOP and an explicit MAIN supply fixture

The board now retains M4 SLEEPDEEP and gates modeled MCU clocks at actual
WFI/WFE entry. SysTick, fourteen timers, SPI transmit deadlines and DMA pumping
pause while the independent RTC continues. Configured EXTI interrupts restore
clocks before reaching NVIC; configured EXTI events release WFE. Timer counters
and deadlines retain their phase instead of accumulating matches during STOP.
Other boards keep QEMU's former SLEEPDEEP behavior. Standby, oscillator/voltage
accuracy and complete peripheral clock qualification remain open.

Twelve synthetic actual-board checks cover clock gating, a non-integral-second
RTC interval, event-only wake, rejected falling edges and ordinary sleep. The
original EX now enters and leaves STOP twice, resamples the running main-switch
byte after the declared wake contact and executes further output configuration.
The STOP-only replay passes 210 harness checks; MAIN stays parked because its
power/reset connection is separate from an interrupt.

`--experimental-main-supply-pin C1` on `tools/run_native.py` selects an explicit
virtual supply connection. It is disabled by default. The output must be in
GPIO output mode. The initial fixture is powered; the first high arms it.
Subsequent low stops the A53s; return high resets GIC and boots CPU0 through
its architectural reset vector. Stock MAIN starts its other cores. EX, virtual
card and RAM remain retained. Repeated same-level writes do not issue resets.
The IO snapshot exposes selected-supply state and cut/reset counters read-only.
This is a declared functional connection, not recovered physical Z8 wiring or
a complete electrical power-domain/fastboot model.

Twenty-two synthetic checks cover the default unconnected case, selected and
neighbor outputs, two cuts/resets, retained MAIN RAM, independent EX execution,
idempotence and invalid pin rejection. An original MAIN/EX single-cycle run
cuts at 21.146 and returns at 24.050 virtual seconds, then resumes Photo and
RAW frames without resetting EX. At 45.004 seconds it reaches 579 RAW frames,
909 MAIN/889 EX frames, zero bad frames, 416 passing harness checks and clean
owned shutdown. No host switch reply, firmware instruction/RAM patch or manual
PC assignment supplies restart; CPU reset uses the configured reset vector.

The separately qualified cold Session restart remains available without this
experimental connection. Physical wiring, complete MAIN peripheral-domain
reset/retention and recording retain separate gates. Live-profile capture
across one declared supply cycle is qualified below.

A second original run uses the production CLI fixture for two cut/return cycles.
Both architectural resets succeed; EX's startup reset count remains one. At
70.013 virtual seconds the run has 703 RAW frames, 1,374 MAIN/1,342 EX frames,
zero bad frames, 808 passing harness checks and clean owned stop. Original UI
state responds to Menu after both restarts (6→1), and half returns it to 6 with
Photo/RAW recovery. Immediate contact snapshots do not independently qualify
fully rendered Menu contents. The read-only counters report two supply cuts,
two resets and four STOP entries/exits.

### Desktop live-profile idle wake and recapture

The desktop now forwards an explicit `experimental_main_supply_pin` through
the native CLI validator. Only the C1 fixture enables the shared Wake camera
button and AppKit command. Fresh observed supply-off admits one request:
`C5=0:G0=1`, then `G0=0` after 0.5 virtual seconds. Ordinary controls remain
paused until a newer supply reset, firmware readiness and both RAW/LCD frame
counters advance beyond their pre-wake values. Cancel releases the pulse;
a 30-virtual-second host deadline reports an unconfirmed outcome without retry.
Unwired terminal pause remains sticky. Cold Session restart is separate.

A native AppKit run at default timing completes HE★ → Movie → Photo, then
idles into supply cut at 124.503192775 virtual seconds. Camera → Wake camera
issues its contact at 141.419851278; original EX returns the supply at
141.430237427 and MAIN boots through its architectural reset vector. RAW
advances by 150.33544133 and LCD by 153.335520923 seconds, before the ordinary
half-shutter contact at 153.734253573. No extra half-key is needed to produce
those first fresh frames. The initial host gate had unlocked at 147.38605682
on general firmware readiness; the final gate additionally requires fresh
RAW/LCD progress so retained counters cannot unlock it early.

Two further HE★ captures surround another Movie/Photo interval after wake.
The last capture lease completes at 199.897558623 seconds. All three files
pass complete RAW/three-JPEG, producer and receiver audits, with zero input
mismatches and the established 26/3.0295569033116294 maximum/mean synthetic
error. All 1,041 runtime checks pass. At clean native Stop the run retains one
EX startup reset, one MAIN supply cut/reset, two STOP entries/wakes, zero bad
frames, 2,946 RAW / 4,401 LCD frames and 362 functional Movie frames. Camera
menu capture/mode/wake actions, Cmd-1/Cmd-2, the capture button and busy/stop
control disabling were exercised. Physical power wiring, complete peripheral
reset retention, recording and physical codec/timing equivalence remain open.

A separate production replay verifies the final fresh-frame gate: idle-off at
45.441170446 virtual seconds retains 999 RAW / 934 LCD frames. Wake is delivered
at 45.816677446 and its contact released at 46.31753579. Controls remain paused
through reset and firmware readiness until fresh counters reach 1,092 RAW /
936 LCD frames; the lease completes at 57.758548423. All 347 checks pass with
one supply cut/reset, one EX startup reset, zero bad frames and clean stop.
This final-gate control makes no exposure and retains separate scope from the
three audited desktop HE★ files.

## Movie recording preparation frontier

`tools/native-movie-recording-contacts.json` enters Movie, presses/releases its
Record key at virtual 30/30.4 seconds, sends a second press/release at 40/40.4
and returns the selector to Photo at 50. The original EX input is expander
`0x22` bit 12, serialized at report byte nine. Original MAIN consumes it into
SW1 mask `0x2000` (`ID_SW1_MOVIE`). The bounded native input check observes
press at 30.007462813 and release at 30.417624705 seconds.

Recording preparation needs an additional explicit ROM input:
`--experimental-movie-selector10` with all five Movie-profile options. It
supplies index ten as one, without factory calibration. The original lookup
uses a mode-derived index; its incoming argument five is a different value.
Supplying the HE index-five byte does not repair the recording lookup. Without
the index-ten input, CAPTG faults at `0x41170D84`; the later `0x15080014`
unknown read is part of its diagnostic dump.

With index ten supplied, the original driver reaches a 3840×2160 RGB header
START. It programs all four rows with the same paired internal port tokens
`0xE0000000` and `0xE0001680`, matching half the 11,520-byte supplier pitch.
The model now admits this observed layout with strict geometry, complete
configuration and paired-plane checks. The original `0x103` to `0x101` control
RMW remains unchanged. The native continuation passes this header and reaches
NR reset ID `0x4A`, bank eight bit 23. The explicit NR initialization/reset
profile has separate continuation checks; no encoded movie, card closure or
saved-file playback is qualified by these preparation results. The optional
host codec receives zero commands in the earlier failed controls.
