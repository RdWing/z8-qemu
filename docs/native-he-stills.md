# Native Z8 HE stills

Original Z8 C3.11 MAIN with a declared host controller peer can save one HE or
HE★ NEF per cold boot with the opt-in
functional HE receiver and explicit synthetic sensor/ROM preparation inputs.
The original-EX attachment has separate [capture acceptance](native-mcu.md);
these host-peer results do not transfer to it. Repeated ordinary HE with live
preview has its own [opt-in profile and acceptance](#source-readiness-after-capture-cleanup).
The guest constructs the file and writes the virtual card. The host extracts
initialized file bytes without repairing or replacing the container.

| Original RAW recording choice | NEF label | File bytes | RAW strip bytes |
| --- | ---: | ---: | ---: |
| High efficiency★ | 14 | 29,324,288 | 28,565,504 |
| High efficiency | 13 | 17,897,984 | 17,139,200 |

Both strips start at byte 758,784 and decode all 45,705,600 samples at
8280×5520. The supplied 320×240 RGGB fixture is expanded by Bayer-cell
resampling with conversion `min(16383,(v*16383+2047)//4095)`. Maximum error
is 26 and mean absolute error 3.029557 on the 14-bit scale. Both modes decode
identically for this simple fixture; this does not compare photographic quality.
Regular HE's saved strip exactly matches the receiver DMA snapshot, and its
packed14 producer matches all scaled sensor samples. The embedded 160×120,
640×424 and 8256×5504 JPEGs also decode.

The finite FIFO writes the complete HE buffer before data causes 6. After
original W1C, the native driver holds the receiver and requests STOP. The model
requires acknowledged HE output, no pending data owners and a stopped primary
source before posting end cause 8. Original W1C retires that stop. It is separate
from the continuous movie receiver's drain contract. Its timer starts only on
STOP, preserving pre-capture scheduling. Source tests reject early and duplicate
stop requests and preserve unrelated pending causes.

Use the existing capture command with `--experimental-he-still` and the three
explicit preparation/selector/timed-single flags. The default native setting is
HE★; regular HE uses the menu sequence in `tools/he-capture-profiles.json`.
All firmware, sensor frames, virtual cards and output directories remain local.

Build the bounded read-only decoder with a C++17 compiler:

```sh
c++ -std=c++17 -O2 -I qemu -I qemu/nikon-he-public \
  tools/decode_he.cpp qemu/nikon-he-runtime.cpp qemu/nikon-he-public/*.cpp \
  -o /path/to/decode_he
python3 tools/audit_he_nef.py /path/to/DSC_0001.NEF \
  --output /path/to/new-audit --decoder /path/to/decode_he --previews
python3 tools/audit_he_pixels.py --run /path/to/capture-run \
  --audit /path/to/new-audit --raw /path/to/synthetic.raw
```

The container audit needs ExifTool, preview decoding needs Pillow, and the pixel
comparison needs NumPy. The codec is an authored functional forward model and a
pinned public inverse. Nikon encoder microcode, physical ISP/color equivalence,
movie recording and physical-camera quality remain unqualified. Host-peer
repeat capture remains separate from the original-EX acceptance below. Stock LibRaw builds may lack the HE decode path;
opening previews alone is not RAW decoding.


## Original EX source-start timing

Original MAIN/EX now supplies finite input from the guest's SIF source START,
independently of the preview channel bitmap. The model binds the group-0 rising
edge after FRONT preparation to the armed D980 descriptor's enable generation.
It requires the explicit native MCU/still/timed-single models, active units
`0x401e`, no reset/video owner and an observed source configuration. Stale
starts and source STOP cannot complete another request. The host-peer periodic
path retains its bitmap `0x201` gate.

The earlier model spent its 64 attempts before source admission: one baseline
trace cancelled at 51.868495 virtual seconds, before MAIN enabled `0x201` at
52.650659. Waiting polls are now counted separately from admitted DMA attempts.
That correction alone saves a file but retains the reset-error screen. The
native SIF trigger instead supplies the complete 80,017,920-byte frame one
33,333,333-ns pacing interval after START, with zero waiting polls and unchanged
control `0x4000`. This is functional virtual input, not measured sensor timing.
The SfltDriver source guard remains intact.

The original-EX HE★ file has the same 29,324,288-byte container and
28,565,504-byte strip as the host-peer case above. Ordinary HE independently
writes 17,897,984 / 17,139,200 bytes through stock EX menu inputs. Full inverse
decoding, all three previews, exact receiver equality and all 45,705,600 packed14
producer samples pass. Early input alone retained a shutter-release reset error. The explicit native
HE profile now also connects MAIN capture-request GPIO to EX input and actual
EX response output back to MAIN. Original EX supplies the response; the model
adds no timed acknowledgement, packet reply or firmware-state patch. Baseline
and accelerated runs return to Photo without the error. Three consecutive
HE★ captures in one boot each pass full producer, receiver, inverse and preview
audits. Ordinary HE independently passes the same checks. This qualifies bounded
virtual capture/recovery, not physical wiring or exposure timing.

## Reproduce original-EX capture

Start with a fresh host-created exFAT card and the default fresh Photo state.
The replay commits the stock date editor, selects RAW, then applies separately
declared EX and MAIN release contacts. All four HE preparation options and the
complete experimental Movie profile are explicit prerequisites. The two ROM
selector bytes are synthetic inputs, not recovered factory calibration.

```sh
python3 tools/run_native.py --firmware /private/MAIN.bi --mcu /private/EX.bi \
  --qemu /path/to/qemu-system-aarch64 --raw /private/synthetic.raw \
  --card /private/fresh-card.raw --output /private/new-native-he \
  --mcu-pins G1=1:G13=1:G14=1:G15=1 --port 0 \
  --seconds 1800 --virtual-seconds 66 \
  --contact-replay tools/native-he-capture-contacts.json \
  --experimental-he-still --experimental-preparation-profile \
  --experimental-capture-selector5 --experimental-timed-single \
  --experimental-shared221 --experimental-boundary-inputs \
  --experimental-sensor-source-clock --experimental-yuv-channels \
  --experimental-movie-selector16
```

The complete Movie options supply required device models; HE preparation does
not qualify combined Movie live view. Interactive HE sessions disable mode
selection and direct users to a separate Movie session.

This uses the production default `icount shift=0`; wall time and virtual time
are separate bounds. The HE★ replay delivers 100 external contact actions.
Ordinary HE uses `tools/native-he-regular-contacts.json` with
`--virtual-seconds 75`. The native HE profile also enables the existing guarded
alternate SfltDriver bank, retaining fresh-frame, descriptor, pending-owner and
original W1C checks. The explicit profile also enables `mcu-capture-sync-wires`; outside this profile
the wiring stays off. `tools/native-he-recovery-contacts.json` with
`--virtual-seconds 102` supplies three release cycles and now saves three
consecutive HE★ files without an intervening reset action.

For interactive native controls, use `--native-controls` instead of
`--contact-replay`. The same stock date/RAW preparation runs before enabling
**Capture photo** (C), with paired contact delivery, duplicate-request exclusion
and actual output/STOP acknowledgement. Stop remains available during startup
and capture. The macOS session config exposes this through
`experimental_native_he: true`; see the [desktop recipe](../desktop/README.md#experimental-original-ex-he-capture).

After the emulator stops, extract actual initialized card bytes and run the
container/RAW audits above:

```sh
python3 tools/extract_card_file.py --volume /private/fresh-card.raw \
  --file DCIM/100NCZ_8/DSC_0001.NEF --output /private/new-native-he/DSC_0001.NEF
```

The launcher records each acknowledged HE output and sensor buffer under
`he_capture_snapshots`, with a sixteen-capture bound. The first snapshot retains
the older `he_snapshots` alias. For another saved file, pass
`--capture-index 2` to `audit_he_pixels.py` to select that actual producer and
receiver rather than reusing the first snapshot. A harness pass or saved
preview alone does not establish RAW decoding or normal capture recovery.

## Preparation and preview boundary

The preparation fixture is a global ROM input, not a per-shot switch. A
read-only trace observes the original bank-8 reader consuming byte
`0x45a403e7`. In an accelerated diagnostic with that byte left at zero, Photo
produces 814 continuous frames, but the normal preparation branch submits a
packed12 descriptor and produces no finite input frame, HE job or NEF by
66.065 virtual seconds. Removing the fixture therefore does not qualify a
combined capture/live-view profile. Keep the existing explicit HE recipe and
its separate Movie-session boundary. Accelerated timing controls do not
replace production-timing recovery checks.

A prior production-timing power control completes one MAIN supply cut and
restart before capture with HE preparation active. After stock date/RAW setup
and one fully audited HE★ file, the off/on control instead reaches 116.019
virtual seconds with no supply cut/reset or second capture. The initial
controller request/reply completes, but the later off request and terminal park
are absent. Finite input and HE data/STOP ownership are already retired in a
separate read-only diagnostic. The missing audio TX consumer below explains
the retained sound owner. Capture across a MAIN restart remains unqualified.

## Finite sound transfer and shutdown

The experimental native HE profile includes `serial5-tx-drain-model`. The
original firmware submits a finite sound buffer during capture; retaining its
registers without consuming its DMA leaves the audio service busy and prevents
shutdown. The new sink reads the mapped source bytes, records their SHA-256,
then completes the existing DMA descriptor. The original ISR, sound callback,
stop request and shutdown worker own the subsequent releases.

This model covers channel 0, request 27, aligned single 32-bit transfers to its
TX FIFO. It requires the explicit serial and bus fixtures and the guest TX
request. It stays off outside the HE profile. Cancellation or an invalid,
ambiguous or unmapped descriptor produces no bytes or completion. The session
is bounded to 16 MiB and 1,024 descriptors; the functional completion delay is
one virtual millisecond, not a measured sample rate. `serial5-tx-drain-state`
reports counts, source address, byte hash, pending request and fault state.
There is no DAC output or physical sound-quality qualification.

The actual-board check needs no Nikon inputs:

```sh
python3 tests/check_audio_tx.py --qemu /path/to/qemu-system-aarch64 \
  --output /path/to/new-audio-tx-check
```

All 45 byte-transfer, status, cancellation and rejection checks pass. An
original-firmware accelerated replay now clears both retained busy bits,
completes the original suspend callback and cuts MAIN supply after an audited
HE★ exposure. Its extra EX resets and one bad frame keep it a diagnostic.

A separate production-timing replay on the final build passes all 487 checks.
After one HE★ exposure, MAIN supply cuts at 70.190284447 virtual seconds and
returns at 100.015244543 with architectural reset. Original EX remains running;
its reset count is one, with 2,423 MAIN / 2,417 EX frames and zero bad frames.
Menu opens after restart, and half-press returns to the Photo screen. The saved
29,324,288-byte NEF survives the cycle and passes all 45,705,600 RAW samples,
three JPEG preview decodes, exact receiver/strip comparison and zero producer
input mismatches. Maximum/mean error against the supplied 14-bit frame is
26 / 3.0295569033116294. The audio sink consumes 47 descriptors / 451,200 bytes
without fault. This qualifies this modeled capture/off/restart sequence;
continuous HE live view and a second exposure across restart remain open.
The fresh desktop bundle also builds and passes strict signature verification.


## Finite input while preview runs

The existing, default-off `primary-d980-live-single-model` can now consume one
later periodic source frame for the observed original-EX normal-preparation
profile. It requires a fresh prepared finite request, matching enable generation,
active units `0x77F7F`, source control `0x704B`, a running source and the complete
8280×5520 descriptor: format 2 with 12,448-byte rows, or format 1 with
14,496-byte rows. Descriptor validation still
checks mapped destinations and capacity. Reset, Movie input, another geometry,
a stopped source or a stale generation cannot use this additional path.

The byte writer completes before the existing finite-frame notifications.
It changes neither the guest source bitmap nor firmware callbacks. The explicit
live-single option remains disabled in the supported HE profile. Packed12
packing, frame timing and this source-to-capture join are functional hypotheses.
Accelerated original-firmware controls transfer one 68,712,960-byte frame
and continue producing Photo frames. A complete RAM snapshot matches all
45,705,600 supplied sensor samples under the declared packed12 conversion,
with zero nonzero padding bytes. No HE encoder job or saved NEF follows.
The final bounded build passes 601 transport/runtime checks with 814 continuous
RAW frames, one EX reset and zero bad frames. The finite request completes once
with one admitted attempt. The parameter units are active, while the modeled
downstream processing consumers remain unused. Configuration-only diagnostic counters do not prove
that original firmware failed to start those units. The final extension also
cancels after 64 refused DMA attempts, without completing an unwritten frame.
A separate production-default `icount shift=0,sleep=on` replay passes all 446
checks through 60 virtual seconds. It completes the finite request once with
one admitted attempt, keeps 641 continuous RAW frames, and has one EX reset,
zero bad frames and clean owned stop. All 45,705,600 RAM samples and row padding
match the accelerated result exactly. This qualifies the modeled input under
the default timing profile; no HE request/job or saved NEF follows.

A read-only IRQ control also confirms that firmware consumes the source
notifications. The retained RAW DMA done bit is excluded by its guest enable
mask, so its zero direct ACK count is expected. An additional byte-backed
input-ready notification is acknowledged but does not configure the later
image-processing request; that prototype is excluded. The next join remains
the original primary-unit pixel/descriptor and request-admission chain.
Combined HE capture/live-view acceptance remains open.

Read-only matrix-worker controls observe 2,039 completed preview/settings
actions in the normal branch, while the working HE profile completes 81
actions including capture processing and storage. However, inspection of the
actual screens finds different effective output settings: the normal replay
ends at JPEG normal/small, while the supported HE replay ends at RAW/large.
The fixed contact sequence navigates different menu states. These controls
therefore do not isolate an HE request failure. The completed packed12 RAM
transfer remains valid input evidence; the absence of an HE job in that JPEG
run cannot qualify a missing HE processing transition. RAW/HE selection must
be verified before the combined capture test.

A screen-confirmed RAW run identifies a separate admission defect: its format-1,
14,496-byte-pitch descriptor remained armed because the running-source guard
accepted only format 2. The guard now admits both observed packing/pitch pairs,
with the same source, generation, geometry and mapped-descriptor checks.
Crossed packing/pitch pairs remain rejected. In an accelerated original-MAIN/EX
control with pauses between menu contacts, RAW L is verified before shutter
release. All 564 checks pass; one request transfers all 80,017,920 bytes in
one attempt, with zero source waits/cancellations, 756 continuous RAW frames,
one EX reset, zero bad frames and clean owned stop. HE still has no request/job
or saved file, and the capture matrix remains unqueued. This qualifies the
packed14 input admission, not the remaining primary-processing completion or
combined HE/live-preview workflow. The updated build also preserves the
packed12 control: all 45,705,600 samples and row padding match its prior hash.

A second screen-confirmed packed14 control also passes the complete mapped-RAM
comparison: all 45,705,600 samples match, every padding byte is zero, and the
80,017,920-byte buffer hash is
`543b9eeb0f212c277a25bda41fb1bb631e38d61e4d7fe5f4349bfb8bdd4d33a8`.
Its 392 checks pass with 397 continuous RAW frames and clean owned stop.
The worker's final zero return can include an internal input timeout, so it
must not be treated as proof of successful processing. Combined HE/live
preview remains open.


Further private notification controls separate preview progress from capture
request creation. A screen-confirmed RAW control passes 649 checks and the full
packed14 RAM comparison. Repeated primary-output waits return success, with
618 continuous RAW frames, but no HE job follows. A read-only request trace
then confirms the supported HE control enters the capture constructor, whereas
the combined preview control does not enter that handler during the observed
interval. The interrupt prototypes remain excluded: a consumed notification
and successful preview wait do not establish a capture-processing request.
The next unresolved transition is the stock capture controller's producer path.


### Capture countdown with live preview

A screen-confirmed RAW L/High efficiency trace finds an earlier scheduling
stall. The still preparation selects an external-ROM timing slot missing from
the synthetic inputs. Adding the existing synthetic unit 1,200 to that slot
changes a wrapped 65,536-frame plan to five frames. These values are functional
model inputs, not recovered factory calibration.

Finite RAW ownership also suppressed the periodic channel clock after its one
complete DMA. The explicit live-single model now resumes that clock only after
the current input epoch completes, with no request armed or reset/stop active.
RAW DMA and source notifications remain finite. The native trace then counts
five frames down to the original zero callback and advances capture state.
One HE job produces 17,139,200 acknowledged bytes after one 80,017,920-byte
input transfer. The initial clock-only run stops at receiver STOP before file creation or
preview recovery; it is not an end-to-end capture pass.


The receiver STOP guard now recognizes a drained current-epoch finite input
while the shared preview unit remains enabled. It still requires acknowledged
HE output, held receiver, no armed input, matching epoch, and no reset/stop or
continuous-receiver owner. The screen-verified single-capture control uses accelerated
`icount shift=3,sleep=on` and passes all 473 checks, has one input request/frame/attempt, zero waits/cancellations, one HE job
and one acknowledged receiver STOP, one EX reset, zero bad frames and clean
owned stop. RAW/LCD counters advance from 582/1,926 after capture to 819/2,163
at the final sample, with the RAW L shooting screen visible.

The guest-written High efficiency NEF is 17,898,496 initialized bytes, tag 13,
with its 17,139,200-byte strip at byte 759,296. All 45,705,600 samples and the
160×120, 640×424 and 8256×5504 JPEGs decode. The saved strip equals the actual
receiver snapshot; all producer samples match the supplied synthetic source.
Decoded maximum/mean absolute error is 26/3.0295569033116294 in 14-bit units.
This control uses preparation input `0x45A403E7=0`, with
`primary-d980-live-single-model=on` and `raw-pipeline-input-pair-model=on`
in addition to the explicit native HE/shared models. The supported HE recipe
keeps its existing preparation and live-single default. This qualifies one
ordinary HE capture with continuing preview under the explicit accelerated
profile, not physical imaging, default-timing acceptance or repeated use.

### Rearming a finite input while preview stays enabled

The second-release trace resubmits its descriptor while the shared primary
unit remains enabled. The finite-input epoch previously advanced only on unit
enable, so the later FRONT preparation could not arm a new input. The explicit
live-single model now renews that epoch on a genuine FRONT `2→3` transition
with a newer, valid submitted descriptor and retired previous HE data/STOP.
It records the submission actually latched with the completed DMA, rather than
a later shadow submission. A completed input must have its own acknowledged
HE job and STOP before another input can be admitted.

Reset/stop, prepared or armed input, continuous receiver work, an enabled old
writer IRQ and invalid DMA spans refuse renewal. The renewed descriptor still
passes through the ordinary full RAW transfer before completion; renewal itself
does no pixel work or guest-state writes. The existing live-single option stays
default-off. This is a functional latch boundary, not measured hardware timing.

Native repetition uses both release stages from `tools/native_inputs.py`:
half/full/full-release/half-release at offsets 0/2/6/8 virtual seconds, followed
by recovery time. Simultaneous full/half release controls do not isolate an
input-notification defect. Host tests cover duplicate FRONT transitions, stale
and later shadow submissions, HE/STOP ownership, enabled pending IRQs, reset,
invalid spans and subsequent renewed inputs.

Before the source-boundary correction below, a four-exposure diagnostic produces
four finite DMA/HE/STOP transactions and
four guest NEFs. Every file decodes all 45,705,600 RAW samples and three JPEGs,
equals its own receiver strip, and has zero producer-input mismatches. The
first three exposures return capture permission and advance live preview.
However, the fourth shows the firmware restart-error screen despite passing
829 transport checks. Fresh controls with the per-input HE-count guard also stall before the second
descriptor submission, so those controls did not qualify native renewal with the added guard. These controls remain failed native acceptance evidence; transport counters
and valid files alone do not qualify repeat shooting.


### Source readiness after capture cleanup

The second request can be dropped before descriptor submission when a source
ready notification arrives before the preceding capture clears it. A later
source watchdog can then produce the restart-error screen. Restoring an event
bit or suppressing the error would bypass the original capture admission.

The explicit native finite live-preview profile now retains the capture pad's
masked control state. While that envelope is asserted, completed preview pixels
continue but do not publish a new second-bank source-ready bit four. The first
completed output after release starts an ungated frame; the next completed
output may publish readiness. This places the notification after capture
cleanup. Short pad assertions between output ticks also invalidate that frame,
and an unfinished current HE data/STOP owner keeps the boundary held.

After that input's own HE data and STOP retire, the running preview source can
resume its configured upper source boundaries. A newer prepared/armed input,
frame/job mismatch, pending receiver, reset or stop keeps them held. Finite RAW
DMA remains one frame per epoch. Source retirement and readiness ordering are
separate from existing pending interrupts, W1C and RAW/LCD pixel output.

This connection requires the native MCU, Photo, timed-single, HE receiver and
finite live-single models. Other profiles retain their previous source events.
`raw-pipeline-source-boundary-state` reports the masked pad, held boundary and
deferred-frame count. The connection and frame pacing are functional models;
the physical pad assignment and Nikon encoder arithmetic remain unverified.

Longer controls also require the existing `backend-program-epoch-model=on`:
replace the opaque configuration program after its original stopped reset,
rather than append every exposure to a cumulative 64-word inspection buffer.
That bound is an emulator inventory limit, not a measured hardware FIFO size.
Program words remain opaque and no codec instructions are executed.


The CLI exposes this combination as `--experimental-he-live-preview`, together
with all four native HE and complete Movie device-profile options above. It
selects preparation byte zero, finite live-single input, RAW input-pair
completion and stopped-program replacement. The earlier HE preparation recipe
retains byte one and its existing behavior. Mode switching stays disabled in
both HE sessions.

For four ordinary HE releases, use the command above with these replacements:

```sh
  --experimental-he-live-preview \
  --contact-replay tools/native-he-live-contacts.json --virtual-seconds 136 --seconds 3600
```

This replay contains the stock date and RAW/ordinary-HE menu preparation,
followed by separately declared half/full/full-release/half-release contacts.
Use a fresh card and fresh Photo state; menu sequences are state dependent.


The shared primary stop guard also recognizes the original Photo idle sequence:
a C1 supplier may remain active while held. Only the observed `0x400e` request
and hold, a current completed finite epoch, acknowledged HE data/STOP and the
native live-Photo profile can use that exception. Its completed D980 writer
cause may remain masked; the validated reset kick cancels only that exact
masked status. Enabled IRQs, another status bit or unfinished input/HE work
still refuse reset. The cancellation retains RAM bytes and never increments
IRQ ACKs. Other pixel/receiver/IRQ guards and original W1C ownership remain.


A fresh original-MAIN/EX control on the reset-corrected build completes eight
ordinary HE captures at accelerated `icount shift=3`: all 783 transport checks
pass, finite inputs/HE data/STOP ACKs each reach eight, and every release returns
to ready Photo with advancing preview. It ends at 184.283921744 virtual seconds
with 3,591 RAW / 5,131 LCD frames, one EX reset, zero bad frames and clean stop.
A separate four-capture public replay at default `shift=0` passes 711 checks
and ends ready with 2,242 RAW / 3,717 LCD frames, one EX reset and zero bad
frames. That capture control precedes the isolated idle-only status-cancellation
change; the later idle control below uses the reset-corrected binary.

The corrected accelerated idle-source control completes two captures, idles
for 30 virtual seconds, cancels one retired masked writer status at the reset
kick, then completes a third capture after half/release contacts. Its 911
checks and clean stop pass, with all three data/STOP owners retired and preview
advancing. EX also performs a second system reset during the long idle, while
MAIN remains running. Read-only tracing places MAIN in the settings-write
critical section while EX awaits its request completion. This accelerated
control does not qualify controller continuity.

A matching default-clock control completes two HE captures, then idles for
35 virtual seconds. All 544 transport checks pass, with one startup EX reset,
zero bad frames and a clean stop at 146.166611946 virtual seconds. MAIN
finishes the settings write and reaches its parked shutdown state; EX disables
the periodic request instead of expiring it. Both saved files pass full RAW,
JPEG, producer and receiver audits. This control has no explicit MAIN-supply
connection: half/release contacts leave MAIN parked, so wake and recapture
remain unqualified. No timeout, response or reset behavior was overridden.

All fifteen files from these three controls independently decode all 45,705,600
RAW samples and all three JPEGs, equal their corresponding receiver strips,
and have zero producer-input mismatches. Error against the fixed supplied
synthetic frame remains maximum 26 and mean 3.0295569033116294 in 14-bit units.
Movie transition/recovery and physical sensor/ISP/encoder equivalence remain
open.

A separate HE★ live-preview control completes three consecutive captures on
the same reset-corrected binary. All 556 transport checks pass; each release
returns to ready Photo with its finite input, data ACK and STOP ACK retired.
The final sample at 119.285213056 virtual seconds has 1,639 RAW / 3,194 LCD
frames, one startup EX reset and zero bad frames; the owned process stops
cleanly. All three 29,324,800-byte NEFs have compression tag 14 and a
28,565,504-byte RAW strip at offset 759,296. Each fully decodes 45,705,600
samples and three JPEGs, matches its receiver strip and has zero producer-input
mismatches. Error against the fixed synthetic frame is maximum 26 and mean
3.0295569033116294 in 14-bit units.

`tools/native-he-star-live-contacts.json` preserves those external actions,
including the RAW/HE★ menu selection and three shutter cycles. Use it with
`--experimental-he-live-preview` and the complete native HE options above.
The first control used diagnostic `icount shift=3`. The same public replay
at default `shift=0` now passes all 647 checks and completes three HE★ files
with data/STOP ACKs retired and preview advancing after each capture. It ends
ready at 122.029653671 virtual seconds with 1,822 RAW / 3,299 LCD frames, one
startup EX reset, zero bad frames and clean stop. All three files pass the
same full RAW, three-JPEG, producer and receiver audits described above.

The accelerated Movie control remains a failed diagnostic. After two HE captures,
Movie mode is entered and its input descriptor is submitted, but the pipeline
does not start and returning the selector to Photo does not recover preview.
Read-only model snapshots show continued source timing and acknowledged
primary clock events, with no Movie receiver START. Adding another clock
event did not resolve the failure and was discarded. Controls before an
exposure, before HE menu setup and without HE profile options reproduce the
stall at accelerated timing. At the normal clock, the combined profile before
HE exposure produces 78 Movie frames with zero rejects, returns to Photo and
passes 355 checks with clean stop. After two HE★ exposures at the default
clock, a separate failure leaves the source timer unarmed following primary
reset and START. The source-clock model now reevaluates its existing timer on
an accepted source-unit START, preserving a pending deadline and capture-group
enables. `event1508-channel-state.timer_armed` distinguishes scheduling from
configured source eligibility. The repaired run completes and fully audits two
HE★ files, passes 605 transport checks and stops cleanly. Source ticks resume,
but Movie still receives no receiver START and Photo readiness does not return.
The third exposure was therefore not attempted in that timer-only control.

The next normal-clock control reaches the original encoder START, exposing a
separate admission error: Movie explicitly programs continuous mode zero with
encoder selector one, while the model accepted only selector zero. Selector
one is now admitted only with the experimental functional HE transport. The
existing geometry, buffer-range/non-overlap, fresh-input and ownership checks
remain. Configured primary bit2/bit6 notifications also follow the surviving
source clock outside finite HE ownership; they remain explicit functional
inputs, not measured sensor signals. A paired-global-boundary alternative
failed to recover Movie and is excluded.

With both corrections, a fresh original-MAIN/EX run at default `shift=0`
completes two HE★ captures, enters Movie, returns to ready Photo and completes
a third HE★ capture with advancing preview. It passes all 757 checks. Movie
has 95 encoded/decoded frames at 111.118335384 virtual seconds and 97 by
Photo return at 119.118466843 seconds, with zero encoder/decoder rejects.
After the third release at 132.121557543 seconds, Photo is ready, all three
finite inputs and HE data/STOP acknowledgments are retired, and RAW/LCD frame
counts are 1,941/3,414. There is one startup EX reset, zero bad frames and a
clean owned-process stop. All three HE★ files pass the full RAW, three-JPEG,
producer and receiver audits above, with the same bounded synthetic-input
error. No guest instruction, RAM flag, timeout or response is patched.

This qualifies one post-HE Movie/Photo cycle followed by recapture under the
explicit experimental profile. Repeated mixed-mode cycles, desktop combined
mode controls, MAIN supply/wake integration, playable recording and physical
codec/timing equivalence remain open. Interactive HE mode controls stay gated.

Desktop sessions can select this profile with `experimental_he_live_preview: true`
alongside `experimental_native_he: true` and its existing dependencies. The
automatic HE★ setup is the validated replay prefix ending with released
contacts; exposures still require **Capture photo**. Configuration and setup
contract tests cover forwarding, dependency checks and absence of a full-shutter
action during setup.
