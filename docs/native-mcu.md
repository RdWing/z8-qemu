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
128×128 top-panel behavior and its ready delay remain functional fixtures. The
panel received one clear packet and zero line packets in the native run.
The donor mechanical shutter is unarmed and its position pins are not driven.
Exact physical chip identity/clock, remaining Z8 key/lens/power mappings, native
full-shutter capture, encoded recording, idle wake and top-panel drawing remain unqualified.
Movie live view, normal Photo recovery and card-backed review have separate
native acceptance below.
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

`--native-controls --port 0` enables Menu, arrows, OK, i and half-shutter in the
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
| Half-shutter | PG1 | `0x07` |
| Playback | expander `0x23`, bit 5 | `0x44` |
| Photo/Movie | expander `0x23`, bit 10; high/low | `0x57` |

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
half/Menu contacts did not wake it. This is a separate idle-wake gap. Zoom,
repeated still capture and full native controller parity remain unqualified.

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

The desktop does not expose full capture yet: a switch report alone does
not qualify image capture or the separately modeled MAIN half/full GPIO inputs.
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
This narrows the remaining join beyond admission; it does not qualify native
HE capture or the physical connection between EX and MAIN release inputs.


A full-phase-only read-only trace further reaches the UI action with the full
key and clear inhibit/busy/filter checks. Its sequence-permission getter returns
zero, selecting initial sequence 1; the accepted host-peer capture returns one
and selects sequence 3. Only active reason 37 intersects the current mask; active reason 125 is masked.
The probe stops cleanly at virtual 71.270584 with 1,622 MAIN / 1,533 EX frames,
no checksum failures and no image-engine jobs. These are firmware gate
observations; no reason bit or firmware instruction is changed to force a shot.
