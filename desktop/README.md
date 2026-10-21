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
Only public Python/HTML/JSON runtime source is copied into the bundle.

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
top-panel drawing, recording, playback idle wake/zoom, USB/plugins, a firmware console/debug
dock and Linux/Windows desktop bundles remain open.
The Z63 camera skin, rotary-dial map and firmware addresses are not presented as
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


### macOS startup location workaround

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
