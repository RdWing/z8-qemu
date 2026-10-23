# Native Z8 HE stills

Original Z8 C3.11 MAIN with a declared host controller peer can save one HE or
HE★ NEF per cold boot with the opt-in
functional HE receiver and explicit synthetic sensor/ROM preparation inputs.
The original-EX attachment has separate [capture acceptance](native-mcu.md);
these host-peer results do not transfer to it.
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
