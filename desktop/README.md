# Z8 macOS workbench

A native AppKit/WKWebView window reuses the Z8 browser workbench and its input
queue. It launches one isolated emulator session, saves exact guest-display
PNG pixels through a native Save dialog and shows the session files in Finder.
Session → Save session log exports the stopped launcher log to a chosen local
file; the original log remains in place. The command is disabled while a session
is starting or running. It exports the log only, without collecting other inputs.
Closing the window or quitting requests graceful shutdown, then bounds cleanup
of its own process group. It never targets another emulator process.

Build on macOS with Xcode command-line tools:

```sh
python3 desktop/build.py
```

This creates `.local/desktop/Z8.app`, ad-hoc signed for the build host's CPU,
with a macOS 13 deployment target. QEMU, Python and Nikon inputs are not bundled.
Python 3.11 or newer and the built QEMU executable must already be available.
Only runtime source listed in `source-manifest.json` is copied into the bundle,
after fingerprint and privacy-pattern checks. Unlisted local files are excluded;
symlinks and non-source payloads are rejected.

Copy `desktop/example-config.json` to a private location and set absolute paths.
`desktop/example-native-config.json` shows the explicit original-EX Movie/card
configuration; every input path still names a user-supplied local file.
Choose a **new output directory** for every session; the guest owns creation of
that directory. Open the app and select the configuration, or run:

```sh
.local/desktop/Z8.app/Contents/MacOS/Z8 --config /private/session.json
```

`--compact` starts a 680px window. The same responsive workbench, keyboard
shortcuts, native Photo/Movie popup, stale-session handling and token-protected
loopback queue serve both desktop and browser. Sessions choose an unused
loopback port and publish it atomically to `control-endpoint.json` in their
private output directory. The webview only navigates within that origin.

Camera → Switch to Photo / Switch to Movie (Cmd-1 / Cmd-2) offers native
commands alongside the popup. Both use the same guarded input queue, and
the commands stay disabled until the selected controller profile is ready.
The app checks configured input access off the UI thread before starting
Python. If access pauses, Session → Allow input access opens the configured
file picker; Stop emulator cancels startup. A denied file can also open that
exact-input picker. No broader folder permission is requested.

## Controller modes

The default uses the established host MCU peer. Add an existing `card` path
and `"experimental_playback": true` to enable the Playback button / P shortcut.
Without that explicit capability, both the frontend and server reject Playback.
The guest can write the supplied card. Export camera files only after stopping
its session, using the existing card/export tools.

Add an absolute `mcu` path for the original EX03.00 component. Add `"native_controls": true` to
enable the independently qualified Menu, arrows, OK, i and half-shutter
contacts. Original EX owns the resulting messages; the app changes external
contacts only. A virtual card and `experimental_playback` enable Play, with
`experimental_shared221`, `experimental_boundary_inputs` and
`experimental_sensor_source_clock` also required. All five Movie options below
enable the native Photo/Movie lever. Unsupported buttons stay disabled. Without
that option, native mode is display-only. Stop and window-close own either
session's lifecycle. See the [contact map and limits](../docs/native-mcu.md).

The experimental Movie live-view recipe is also available by setting
all five `experimental_shared221`, `experimental_boundary_inputs`,
`experimental_yuv_channels`, `experimental_movie_selector16` and
`experimental_sensor_source_clock` fields to `true`. These explicit models
have host-peer two-cycle acceptance and separate original-EX live-view/recovery
acceptance; they do not qualify recording. See the [Movie checkpoint](../docs/z63-backport.md#movie-live-view-and-recovery-checkpoint).

## Checked and remaining

The native macOS build, configuration rejection/recovery, 680px responsive
layout, Photo/Movie popup/Escape, Down input, guest-written NEF playback,
display Save dialog and window-close cleanup were exercised. One desktop
baseline run passed 1,117 harness checks. Private process-group timeout cleanup
and readiness/session/playback admission have firmware-free tests. The strict
frontend audit reports zero findings.

The explicit host-peer Movie profile was exercised from the desktop selector:
667 movie frames, followed by Photo/Menu/half-shutter recovery and 2,366 total
RAW frames at clean window-close shutdown.

Original-EX desktop half-shutter and Menu inputs also reached the native Menu,
with clean owned-process shutdown and zero checksum failures. The shared
workbench separately exercised native Movie/Photo. A rebuilt AppKit window
also completed native Play/half/Menu/half with one 1,396,736-byte review transfer,
fresh Photo frames (518 RAW frames at shutdown), 761 MAIN / 710 EX frames, zero
checksum failures or pixel rejects and clean window-close cleanup. A later native Camera-menu run separately completes Movie→Photo→Menu→half
with 135 Movie frames, matched ISP/source acknowledgments, 870 RAW frames,
1,047 MAIN / 937 EX frames, zero checksum/pixel errors and clean window close.
The native commands avoid depending on popup automation; both use the same
shared selector queue.

This is an initial native desktop integration. Remaining MCU keys/lens/power,
physical top-panel timing, recording, playback idle wake/zoom, USB, format-aware firmware logging, interactive firmware commands
and Linux/Windows desktop bundles remain open. Read-only UART/device diagnostics are available below.
The Z63 camera skin, exposure-mode ADC ladder and unjoined firmware addresses are not presented as
Z8 controls. The experimental native HE profile below adds shared browser,
keyboard and native Camera-menu capture using the qualified paired contacts.


## Firmware power-down

The native controller path can reach the original firmware's terminal SRAM
park after review idle. The workbench recognizes the checked C3.11 CPU states,
pauses camera controls, cancels pending inputs and keeps the last frame.
Session → Restart session (Cmd-Shift-R) provides a cold restart with the same
inputs/card and a fresh output directory. The old owned process exits before
the new session starts. This does not implement physical controller wake or
preserve firmware RAM across a reset.

The native window now passes Stop during a pending background input check,
Cancel in the exact-input picker and Stop during early firmware boot. No output
or launcher log is created by the cancelled preflight. Session → Allow input
access also resumes startup after the exact configured MAIN file is selected.
Picker cancellation reports “Startup cancelled” instead of displaying a misleading file-save error.

Two native Session restarts are verified: after boot cancellation and after
terminal power-down. The first review reaches power-down at virtual 28.784 with
the image retained and controls disabled. Its QEMU stops before the second
session opens a fresh endpoint. The same NEF then displays again, a half-shutter
returns to Photo and RAW frames advance to 419. Each review completes one
1,396,736-byte resize job; both owned sessions stop cleanly with zero checksum
failures. This qualifies cold restart, not firmware wake or fastboot.


The native session-log Save dialog is verified against a stopped original-EX
launcher log: all 103 bytes match the retained source. The command is disabled
while QEMU runs, re-enables after owned shutdown, and Cancel leaves the log in
place. This exports diagnostic text only; it does not export a card or NEF.


## Experimental original-EX HE capture

Set `experimental_native_he: true` together with `mcu`, `native_controls: true`,
a virtual `card` and all five experimental Movie options. The session supplies
the explicit synthetic HE preparation/selector models and recovered sync wires;
original EX produces the command and GPIO replies. It first navigates the stock
date editor and RAW settings. Stop remains available during this preparation.

Add `experimental_he_live_preview: true` to select the live-preview HE profile.
Its stock setup selects RAW/HE★ and ends with the shutter released; no exposure
is automatic. This is the same setup prefix used by the default-clock
three-capture replay. The option requires `experimental_native_he: true`; the
earlier capture profile remains available when it is omitted.

HE capture sessions keep the Photo/Movie selector and native mode commands
disabled. For the separately qualified Movie live-view workflow, start a
session with `experimental_native_he: false`. The five shared/Movie options
are dependencies of the HE model, not combined-preview qualification.

After readiness, use **Capture photo**, **Camera → Capture photo**, or C in the
workbench. One admitted capture holds/release the paired EX/MAIN contacts and
waits for actual HE output/STOP acknowledgement. Other camera inputs and
additional capture requests wait; Stop can always end the owned session. The
queue reports delivered input, not a saved-file claim. If completion cannot be
confirmed, contacts are released and the status directs you to the camera display.
Capture results and per-capture sensor/receiver snapshots remain in session files;
use the [native HE audits](../docs/native-he-stills.md) after shutdown. Native
photo export is available after Stop; see the export operation below.

The native baseline check stopped startup at 2.502 virtual seconds, restarted
the same card, then completed three captures through the Camera menu, C and the
browser button. All three saved NEFs independently pass full RAW/preview and
producer/receiver audits. Playback shows the newly written `DSC_0003.NEF`
through one 1,396,736-byte review job; half-shutter returns to the Photo UI.
This HE profile retains the last preview on that return, so this check does
not qualify fresh continuous Photo pixels. The session passes 372 checks,
1,935 MAIN / 1,855 EX frames, zero checksum failures and clean owned shutdown.


## Export photos from a stopped card

After Stop completes, choose Session → Export photos… and name a **new folder**.
The app copies initialized NEF/JPG/JPEG files under DCIM, retaining their folder
layout. It does not change the virtual card or replace an existing destination.
A progress sheet offers Cancel export; completion reports the photo count and
Show in Finder. Starting another session waits until export finishes. Quitting
cancels export and waits for its worker to stop.

Export requires the stopped session's matching card receipt and a QEMU-compatible
read lease. Persistent-card launches explicitly enable file locking. Another
active writer prevents export; the held lease also prevents a new QEMU writer.
The helper publishes the completed folder atomically, without extraction
sidecars. Limits are 512 photos, 256 MiB per photo and 2 GiB total, with a
five-minute deadline. Incomplete files, unsafe/colliding paths and changed cards
fail without publishing a partial folder. These guards cover cooperating QEMU
writers, not arbitrary programs that ignore file locks.

The actual native Save dialog exported three retained guest HE★ NEFs, each
29,324,288 bytes, byte-identical to their independently audited originals. Cancel
in the destination dialog created no folder. This also passed after a failed
startup whose owned QEMU was confirmed stopped: export is a recovery path, not
a requirement to boot the firmware again. Host tests cover mid-copy cancellation,
existing destinations, malformed/empty cards and worker cleanup. Four additional
firmware-free checks use the actual QEMU binary to verify writer exclusion and
reopening after lease release.

The exact-input picker now advances immediately after selecting the configured
file and ignores the superseded background check. Socket-wait cancellation
reaps the owned QEMU; a native Stop during the pending child launch reports
cancellation at 2.249 seconds from launch and confirms owned cleanup. failures record elapsed time and actual early-exit status.
A separate repository-path native-app startup attempt remains blocked before QEMU initialization
in a macOS XPC filesystem open. The same original-EX configuration starts from
the CLI (control socket in 0.077 seconds). Increasing the deadline to 30 seconds
and removing an inherited bundle identifier did not repair the native launch;
those speculative changes are not retained. The location workaround below
starts the same binary. This host-specific failure is not firmware boot or MCU
acceptance.


### Firmware-free executable preflight

Desktop startup runs the selected QEMU with `--version` before the Python
launcher reads firmware or creates the session directory/log. A ten-second
deadline distinguishes executable failure from guest boot failure. Stop cancels
this check and reaps its owned process group. Cancellation and nonzero exit
remain distinct; there is no automatic relocation or firmware-session retry.
AppKit's existing exact-input access check still precedes Python startup.

Run the same check independently:

```sh
python3 tools/qemu_preflight.py --qemu /absolute/path/to/qemu-system-aarch64
```

A successful result proves only `--version` completion. It does not guarantee
a subsequent launch or repair the intermittent macOS path failure below.
Desktop `--check-only` performs this check before original input validation.

### macOS startup location workaround

The current app disables bytecode writes inside its signed runtime. Rebuild into
a new app directory to repair an older bundle whose resources already changed.
Repository-path QEMU starts in some checked native runs, but two later attempts
still time out before initialization despite a valid, immutable bundle. The
signature fix does not resolve that intermittent host-path failure. The location
control below remains a tested workaround; the underlying macOS cause is open.

If the app times out waiting for QEMU's control socket while the same inputs
work from the CLI, try a QEMU build in a runtime directory outside Documents,
such as `~/Library/Caches/z8-qemu`. `tools/build.py --build-dir` accepts an
absolute directory. Update the configuration's absolute `qemu` path. Keep
firmware, cards and captures separate; no permission setting needs to change.

An identical binary (SHA-256
`8daec4773df0c4fea3e3beac65c01058bb475963d616ab3c96f82b2f5d434a41`)
launched from a private temporary directory publishes its control socket in
0.365 seconds and advances original MAIN/EX execution. The repository-path
launch waits in macOS's XPC initializer. A same-card native cold restart publishes its socket in 0.053 seconds, reaches
ready state with 126 display / 223 RAW frames at virtual 16.257, and exchanges
366 MAIN / 346 EX frames with zero bad frames before clean owned shutdown.
This is a tested location workaround; the
underlying macOS filesystem-access cause remains unresolved. It does not
establish a new firmware-feature or camera acceptance result. Temporary paths
are diagnostic only; use a stable runtime path for a saved configuration.


## Native Camera button commands

Camera → MENU, Half shutter, Playback, i menu, DISP, Up, Down, Left, Right and OK use the same qualified EX
contacts as the page buttons. They work through the native menu without
requiring keyboard focus in the embedded page. Their enabled state follows the
page's actual per-button readiness; Playback still requires a card and model.
Boot, shutdown, disconnect and admitted capture disable the corresponding
commands. Capture admission immediately disables other inputs while its HTTP
request or confirmed job is pending, preserving the server's independent gate.
DISP uses the separately qualified Z8 expander contact; host-peer and display-only sessions keep it disabled.


The native launcher disables Python bytecode writes for sessions, export and
their descendants. Earlier builds wrote `__pycache__` inside the signed runtime
and failed signature verification after use. A compiled production-function
test runs actual parent/child Python imports and verifies the runtime remains
unchanged. Verify app signatures after exercising the runtime as well as after
building. The updated native build also starts the original repository-path
QEMU without relocation; this observation is separate from proving macOS's
internal XPC wait mechanism.


The updated native build completed Camera-menu MENU/half, i-menu/half and
Playback/half using original MAIN/EX. The i settings grid and retained
`DSC_0003.NEF` displayed, with one 1,396,736-byte review job; return to Photo
advanced RAW frames from 920 to 974. The session passed 392 runtime checks,
exchanged 1,223 MAIN / 1,133 EX frames with zero bad frames, and stopped cleanly.
Its original repository-path QEMU socket appeared in 0.049 seconds after cold
restart. Three exported NEFs still match the audited originals exactly.
After both sessions and export, the app has zero pyc files and its strict code
signature check passes. This qualifies these native commands and bounded
recovery; physical display fidelity, idle wake/zoom and HE/Movie preview remain
separate.


## Live diagnostics

Session → Show diagnostics (Cmd-D) opens an independent, read-only window.
Choose MAIN UART TX, QEMU diagnostics, Launcher, or one of the six EX USART
register instances. Pause freezes the visible snapshot while the emulator
continues; Resume follows the latest output. Changing source or restarting
resumes following. Closing this window leaves the camera session running.
Stop retains its logs for inspection; restart changes the diagnostics source
to the new output directory. EX choices are disabled for host-peer sessions.

The view reads at most the latest 128 KiB per half second, off the UI thread,
without changing the complete disk logs. Control bytes are shown as hex escapes;
invalid UTF-8 is replaced in the view only. Missing logs report an explicit
error; FIFOs, directories and symlinks are rejected. This window sends no UART,
monitor or firmware commands. A complete log export still uses the stopped
launcher log action; Show session files exposes the other private logs.

`uart-tx.log` retains the existing MAIN model's stdout TX bytes, combining the
four UART banks at `0x0F000000 + 0x10*n`, data byte `+4`. `stderr.log` contains
modeled-device diagnostics. These are separate streams. Native EX sessions also
create `ex-usart1-tx.log` through `ex-usart6-tx.log` using file-only QEMU character
backends named `z8-ex-usart1` through `z8-ex-usart6`. They attach the existing
STM32 USART1/2/3, UART4/5 and USART6 instances; no physical connector or firmware
console role is assigned. CLI board users can attach those optional names;
absent backends preserve the previous unconnected behavior. No RX input is
created by the desktop file backends.

All 21 actual-board MMIO checks pass, including exact combined MAIN TX bytes,
separation from stderr and unchanged empty/no-RX status. All 95 synthetic MCU
checks pass, including six separate TX streams across zero/one/two resets and
independent A53 execution. A native menu run delivers all five navigation
contacts, drains its queue and passes 300 runtime checks before clean Stop.
These contacts were already qualified through the browser; this closes native
menu access, without adding a new physical input map. The native EX boot emits
one NUL on USART1 and no text on the other streams in the inspected interval;
retaining TX does not establish an interactive command console.

## Optional execution trace plugin

The [read-only trace plugin](../plugins/README.md) supplies explicit call-site
and memory-store observation, shared by the CLI and desktop launcher. Optional
`trace_plugin`, `trace_calls`, `trace_watch`, `trace_cpu`, `trace_limit` and
`trace_per_site` configuration fields select its locally built binary and
bounded observation profile. No plugin is bundled or enabled by default.

Diagnostics → Plugin trace is enabled only for a configured session and uses
the same bounded reader, Pause/Resume and restart-generation rules as other
sources. Startup checks access to the configured plugin; unsupported QEMU/plugin
API combinations fail explicitly. Stop retains the exclusively created private
trace file. This adds read-only diagnostic integration; stock firmware log
decoding, monitor/UART command input, USB and wider MCU bindings remain open.

## Export diagnostic logs

After stopping a session, choose Session → Export diagnostics… to save a new
local ZIP containing the complete available MAIN UART, six EX USART, QEMU,
launcher and plugin logs. The view's 128 KiB limit does not truncate this export.
A manifest lists byte counts, SHA-256 fingerprints and missing optional streams.
The input limit is 512 MiB. Files are copied unchanged, so review the ZIP before
sharing: logs can contain private paths, register values and other local data.
Firmware, cards, captures, result receipts and arbitrary session files are excluded.

The action stays disabled while starting/running; Open/Restart and duplicate
exports wait while it runs. Cancel or Quit unwinds staging. The helper requires
a stopped-session receipt, rejects nonregular/symlink log inputs and changed
files, and publishes a mode-0600 ZIP without replacing an existing destination.
Native destination Cancel and a ten-log export have been checked. Existing
single launcher-log export and stopped-card photo export remain available.

Optional native configuration `"mcu_adc_inputs": "1.1=2048:3.18=4095"` supplies
declared numeric MCU ADC samples. It requires `mcu`; no exposure dial, battery
voltage or physical control name is implied. See [MCU inputs](../docs/native-mcu.md#explicit-adc-inputs).

## EX control panel

Native-EX sessions now show the original controller's 144×168 panel memory
below the camera controls. The model uses Z8's PA1 ready input and eighteen-byte
rows; no Z63 geometry is assumed. The view rotates controller glyphs for reading;
the stored PNG preserves model memory order. The secondary view reports
Display on/off and transferred lines and keeps its last received frame after
disconnection. Host-peer sessions omit it. The main display, input queue, Stop
placement and native Camera commands retain their existing behavior.
See [panel binding and limits](../docs/native-mcu.md#z8-top-panel-binding).


## Native review keys

With original EX controls, a virtual card and the playback model enabled,
Protect key and Delete key are available in the shared workbench and Camera
menu. They press/release the independently mapped Z8 contacts through the
existing queue. Host-peer and display-only profiles keep them disabled.
Neither action has a keyboard shortcut.

These commands retain the firmware's own confirmation flow. Watch the camera
display: Play cancels its Delete question; another Delete press can confirm
removal from the virtual card. The app reports queued input only. Use a copy
of any card whose files you need to preserve.

A finite original-firmware replay shows the protection icon and native Delete
question, confirms one deletion on a disposable card, and returns to fresh
Photo frames. Stopped-card catalogs independently show three original NEFs and
two remaining copied-card NEFs. Shared browser admission/queue checks and the
signed macOS build pass separately; these checks do not qualify protection
persistence, confirmation cancellation or physical buttons.


## Native command dials

Original-EX control sessions offer Main/Sub dial minus and plus buttons plus
matching Camera-menu commands. Each queues one signed dial count through a
complete external quadrature cycle. The existing queue serializes camera inputs;
no firmware message, memory write or automatic retry supplies the count. The
buttons remain disabled in host-peer/display-only sessions, during capture and
after disconnection. No keyboard shortcuts are assigned.

Original-firmware checks cover both signs on both axes, menu movement, submenu
entry/return, a live browser turn and half-shutter recovery. The 80-millisecond
phase cadence is a functional input choice, not physical timing. ISO chords and lens-dependent behavior remain unqualified.

Exposure mode minus/plus uses the same controls and Camera menu. Each action
holds MODE around one Main turn and releases both inputs before another camera
action can run. Stop also releases a cancelled chord. Original firmware retains
Manual mode in the no-electronic-lens fixture; P/S highlights may return to A
on the shooting display. Watch the firmware display for the effective result.

Native browser acceptance covers M → A → M, an actual browser chord, narrow
layout and disabled controls after clean shutdown. The updated host suite has
88 passes and one optional skip; the signed macOS build and signature verify.
New Camera-menu runtime clicks and exact shutter-step consumption remain separate.

Exposure compensation minus/plus adds the corresponding Camera commands and
workbench pair. Each holds the compensation button around a single Main turn,
using MODE's existing finite lease and cancellation rules. The tested firmware
displays third-EV steps; watch its display for the result. These controls do not
write an EV setting directly or guarantee changed sensor/recorded pixels.

Native browser testing covers two increases, two decreases back to zero and
another live-browser increase, with all contacts released and clean shutdown.
The shared cancellation tests, 640px layout, disconnected state and signed app
build pass. The new Camera-menu actions have build/bridge checks; their own
native runtime clicks and restart persistence remain unqualified.
