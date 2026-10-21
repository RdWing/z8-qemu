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

## Controller modes

The default uses the established host MCU peer. Add an existing `card` path
and `"experimental_playback": true` to enable the Playback button / P shortcut.
Without that explicit capability, both the frontend and server reject Playback.
The guest can write the supplied card. Export camera files only after stopping
its session, using the existing card/export tools.

Add an absolute `mcu` path for the original EX03.00 component to inspect native
MAIN/EX startup instead. This mode currently omits card, playback and shared
profile options. It displays original firmware output, identifies original EX
replies, and keeps camera buttons disabled because their Z8 hardware bindings
are not yet qualified. Stop and window-close remain available. It does not
substitute host MCU replies to make controls appear functional.

## Checked and remaining

The native macOS build, configuration rejection/recovery, 680px responsive
layout, Photo/Movie popup/Escape, Down input, guest-written NEF playback,
display Save dialog and window-close cleanup were exercised. One desktop
baseline run passed 1,117 harness checks. Private process-group timeout cleanup
and readiness/session/playback admission have firmware-free tests. The strict
frontend audit reports zero findings.

This is an initial native desktop integration. Native MCU keys/lens/power,
top-panel drawing, recording/recovery, USB/plugins, a firmware console/debug
dock, photo/log export dialogs and Linux/Windows desktop bundles remain open.
The Z63 camera skin, rotary-dial map and firmware addresses are not presented as
Z8 controls. Native HE/HE★ capture remains available through the separately
qualified capture launcher.
