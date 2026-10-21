# Original Z8 EX controller

The optional `mcu-image` attachment runs the user-supplied original Z8 EX03.00
alongside C3.11 MAIN. The existing host-peer launcher remains the capture/menu
baseline. This attachment uses no host MCU replies or firmware instruction
patches. It is experimental and is not a complete native-control workflow.

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
Exact physical chip identity/clock, full Z8 key/lens/power mappings, native
capture, Movie, playback, recovery and top-panel drawing remain unqualified.
No host-peer acceptance transfers to this attachment.

Firmware-free reset checks:

```sh
python tests/check_mcu_reset.py --qemu /path/to/qemu-system-aarch64 \
  --output /tmp/z8-reset-new
```

Clang with AArch64/Thumb targets is required. The script extracts relocation-free
ELF `.text` itself. All 69 checks pass across zero/one/two MCU resets: A53
heartbeat isolation, SRAM/flash/RTC backup retention, ordinary peripheral/core
reset and AIRCR negative controls. This is model validation, not camera capture
qualification.
