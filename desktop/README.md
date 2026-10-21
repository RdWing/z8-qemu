# Z8 macOS workbench

A native AppKit/WKWebView window reuses the Z8 browser workbench and its input
queue. It launches one isolated emulator session, saves exact guest-display
PNG pixels through a native Save dialog and shows the session files in Finder.
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
dock, photo/log export dialogs and Linux/Windows desktop bundles remain open.
The Z63 camera skin, rotary-dial map and firmware addresses are not presented as
Z8 controls. Native HE/HE★ capture remains available through the separately
qualified capture launcher.


## Firmware power-down

The native controller path can reach the original firmware's terminal SRAM
park after review idle. The workbench recognizes the checked C3.11 CPU states,
pauses camera controls, cancels pending inputs and keeps the last frame.
Session → Restart session (Cmd-Shift-R) provides a cold restart with the same
inputs/card and a fresh output directory. The old owned process exits before
the new session starts. This does not implement physical controller wake or
preserve firmware RAM across a reset.

The detector and request cancellation have host tests. Full native-window
restart and startup-cancellation qualification remains pending; this is draft
recovery work. Native Camera-menu Movie/Photo recovery is separately verified.
