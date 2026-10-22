---
version: alpha
name: "Z8 emulator controller"
description: "A local camera control surface centered on Nikon's native LCD output."
colors:
  background: "#101419"
  text: "#eef2f7"
  control: "#263441"
  border: "#75889d"
  focus: "#f9d74c"
typography:
  sans:
    fontFamily: "system-ui, sans-serif"
rounded:
  DEFAULT: "7px"
spacing:
  page: "24px"
  gap: "22px"
components:
  button:
    minHeight: "46px"
  select:
    owner: "native HTML select"
---

# Z8 emulator controller

## Overview

This English local research tool presents the firmware's own display beside a compact button column. Preserve the existing dark camera-monitor layout and familiar D-pad. The LCD is the visual focus; this backport adds a selector without redesigning the page. No Japan-market or multilingual scope is established.

## Colors

Model B: `tools/control.html` owns runtime CSS. This document mirrors its background, text, control, border and keyboard-focus values. Scrollbar thumb and track use the same border/background palette through CSS variables; forced-colors delegates to the system.

## Typography

System UI at 16px/1.5 serves all controls and explanatory text. The 28px title remains secondary to the LCD. No remote fonts or font swaps.

## Layout

1250px maximum, 24px page padding, a flexible LCD plus 180px control column and 22px gap. Below 850px, controls flow below the image. The LCD keeps its 1024/682 aspect ratio. Status and input feedback reserve space.

## Elevation & Depth

Flat dark surfaces with borders. No overlays or decorative shadows.

## Shapes

Seven-pixel control corners and a rectangular LCD. Preserve the established D-pad geometry.

## Components

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
| --- | --- | --- | --- | --- |
| Select/Listbox | native | tools/control.html | Platform popup geometry and keyboard behavior; Photo / Movie | Browser popup, keyboard and selected value |
| Scrollbar | tools/control.html | tools/control.html | Global variables and forced-colors fallback | Static audit and browser |
| Toast | tools/control.html | tools/control.py | Existing input-status live region and inline errors | Browser queued/disconnect states |

`Control` in `tools/control.py` owns the bounded input queue, token validation, readiness and stale-session state. `stream.py` owns MCU delivery. The selector stays latched across button press and release records; applied input state is distinct from the camera's accepted mode. MENU and selector use the same queue and feedback. Offline/stale state disables every camera control while retaining the last image. Arrow shortcuts must not intercept a focused native select or IME composition. This single screen needs no separate UX contract.

## Desktop window

`desktop/Z8.swift` embeds the same workbench in WKWebView. The bundle builder
extracts startup/error CSS directly from `tools/control.html`; it does not own
a second palette or button system. AppKit owns configuration/save dialogs and
menu keyboard behavior. Session → Open configuration is available only while
stopped; Save display requires a live session. Closing the window stops its
owned session. The native shell uses English copy and loopback navigation only. Playback uses
the shared button/queue and requires an explicit virtual card plus model on
both frontend and server. Native EX inspection identifies original controller
replies. Its optional qualified-contact mode enables Menu, arrows, OK, i and
half-shutter. Card/model checks enable Play; the full experimental Movie profile
enables the latched native lever. Capability checks disable unsupported actions.
Display-only native mode retains Stop.
Camera → Switch to Photo / Switch to Movie (Cmd-1 / Cmd-2) call the same
`z8Workbench.selectMode` function as the popup. That function owns readiness,
capability, in-flight and session-error behavior. A same-origin, main-frame
WK message supplies menu enable state; server admission remains authoritative.
`NSMenuItemValidation` applies the native menu rules during boot and shutdown.
Configured input files are opened before child launch; macOS access denial can
be resolved through a native file picker restricted to the configured file.
`--compact` starts the same responsive workbench at 680px width for small screens.

## Motion

No decorative motion. Polling updates status and replaces the LCD image only when its content changes.


## Power-down and restart

The original firmware's terminal SRAM park is distinct from a temporary mode
transition. Its read-only PC/state detector pauses input admission, cancels
queued inputs and retains the last display. Session → Restart session
(Cmd-Shift-R) waits for owned-child shutdown, then starts a fresh output folder
with the same supplied inputs and card. This is a cold session restart; it does
not assert physical MCU power/reset or firmware fastboot support.

AppKit startup defers until launch notification completes. Input checks run off
the UI thread; Session → Allow input access targets only the current configured
file. Stop cancels startup, and generation checks discard stale completions.
Only the active child may update the webview. Python receives a private,
immutable configuration snapshot that is removed after admission or exit.


Session log export is a native Save dialog for the stopped launcher's single
log file. Keep it disabled during startup and execution, copy off the UI thread,
retain the original file, and reject the original path as a destination. Do not
turn this action into an input/card/capture bundle. Cancelling the input-access
picker is startup cancellation, with no launcher or later stale-completion start.


## Experimental native capture

The optional `experimental_native_he` desktop configuration requires original EX
contacts, a virtual card and the complete experimental profile. Startup replays
the stock date/RAW setup before enabling camera input. It retains Stop and the
existing startup/restart cancellation rules throughout preparation.

`Control` owns capture admission, serialization and a monotonic completion ID.
`native_inputs.Inputs` owns the paired EX/MAIN contact lease, final release,
completed-output check and bounded uncertain-outcome recovery. No other camera
input can interleave with an admitted capture. A queued capture is not presented
as a saved photo. A timeout releases contacts and reports that the outcome is
unconfirmed; it never retries automatically. Power-down and shutdown release the
lease. The same `z8Workbench.capturePhoto` API serves the browser button, C
shortcut and AppKit Camera → Capture photo. The WK message only enables the
native command for the current same-origin, main-frame session; server admission
remains authoritative. Unsupported profiles retain disabled capture controls.
No palette, typography, shape, layout token, selector popup or dialog owner changes.

HE preparation and Movie live view have separate capability contracts. An HE
capture session keeps the selector and native mode commands disabled, with
“Use a Movie session for Photo/Movie live view.” Capture readiness remains
independent, so the Camera capture command can be enabled while mode commands
are disabled. A separate Movie session retains its qualified selector workflow.


## Photo export

AppKit owns Session → Export photos…, its new-folder Save dialog, cancellable
progress sheet and count/Show in Finder completion. Export is available only
for a stopped session with a supplied card; Open/Restart wait while it runs.
Quit cancels and waits for cleanup. The helper owns matching-card checks,
QEMU-compatible reader exclusion, worker lifetime and atomic no-replace
publication. Failure/cancellation keeps the source card and any existing
folder intact; no unconfirmed file count is presented as success. Exact-input
picker selection advances startup immediately, retiring the superseded
background read by generation. Native destination Cancel and successful
three-photo export are exercised; worker cancellation and malformed-card paths
have firmware-free host tests. This uses standard AppKit presentation and the
existing workbench; there is no new palette or screen hierarchy.


## Native Camera button commands

Camera → MENU, Half shutter, Playback and i menu call the shared
`z8Workbench.press` function. The page publishes the exact enabled button keys
alongside mode/capture readiness through the existing same-origin main-frame
message. AppKit intersects that set with the known commands and also
requires its owned child and endpoint. Playback keeps its card/model gate;
boot, disconnection and capture admission disable these commands. Button-set
changes must notify AppKit even when mode/capture readiness stays unchanged.
Browser buttons and native commands share local capture-pending/waiting guards
plus server-side serialization. This adds no new EX contact or physical key map.


The AppKit launcher sets `PYTHONDONTWRITEBYTECODE=1` in both session and export
process environments, preserving other environment values. Every spawned
Python descendant inherits this policy. Bundled runtime imports must never
modify signed resources; verify the bundle signature after running sessions
and export, not just immediately after building.


## Read-only native diagnostics

AppKit owns a separate Session → Show diagnostics window, source popup,
Pause/Resume and selectable monospaced text. Use platform colors and controls;
the camera webview retains its canonical stylesheet. The popup distinguishes
MAIN UART TX, QEMU diagnostics, Launcher and the six EX USART instances. Disable
EX choices without a native attachment. Plain-text snapshots read the last
128 KiB off-thread every half second; missing or nonregular files report an
explicit error. Escape nonprinting control bytes and replace invalid UTF-8 only
in the view; full disk logs remain intact. Pause invalidates pending reads.
Source changes/restarts resume following, and generation checks discard stale
results. Closing diagnostics leaves the camera running; stopping keeps its
logs inspectable. This is output inspection, with no command-input control.
Camera navigation adds Up/Down/Left/Right/OK through the existing shared bridge,
per-button capability and capture-busy gates. Do not introduce a second queue.

The same native source popup also offers Plugin trace. Enable that choice only
when the session explicitly configures a trace plugin; EX USART choices retain
their independent native-EX gate. Both host-peer and native-EX sessions can
trace. A source becoming unavailable resets selection to MAIN UART TX.
Keep the existing read-only text, bounds, Pause/Resume, stopped inspection and
generation-guarded restart behavior. The configured plugin path joins the
existing exact-input access checks. No new command-input control or visual
token system is introduced.


## Diagnostic ZIP export

Session → Export diagnostics… uses the same AppKit destination, cancellable
progress and completion owner as photo export. It is available only while
stopped. Open/Restart and other exports stay disabled during the operation;
Quit cancels and waits. The ZIP variant selects its file in Finder, while the
photo variant opens its folder. Destination Cancel leaves no export. The Save
dialog explains that exact logs can contain private paths or memory values.
The helper uses a fixed diagnostic filename list, byte/receipt bounds, regular
no-follow inputs and atomic no-replace publication; inputs, results, captures
and arbitrary session files never join this bundle. Existing single launcher-log
export remains distinct. Platform controls and visual tokens remain unchanged.


## EX control panel observation

The shared workbench owns the secondary 144×168 panel image, status and native
capability gate. Place it after the complete main-display/control layout so
Stop and camera controls keep their narrow-screen order and location. Use the
existing palette/border, a 16px heading and pixelated image at its logical size;
AppKit embeds this same view without a second renderer. The PNG preserves model
line/shift order; a clockwise CSS rotation makes the observed glyphs readable.
This view transform does not assert the physical panel mounting. Status names
Display on/off and line count. Host-peer and pre-sample states hide it.
Disconnect preserves the last pixels under the existing disconnected status;
new-session pages start without inherited panel state. No new controls, queues,
menu entries, visual tokens or locale ownership are introduced.


## Additional qualified display control

DISP reuses the existing camera button style, capability set, guarded queue and
AppKit button bridge. Browser button, D shortcut and Camera → DISP have the
same label and enabled state. Its native EX contact is qualified separately;
host-peer and display-only profiles show the disabled button with an explicit
reason. Modified keyboard shortcuts are reserved for the platform. There are
no new visual tokens, dialogs, layout variants or input queues.

The desktop's firmware-free QEMU preflight remains part of existing startup.
Stop and generation guards retain ownership while the child runs `--version`;
a timeout never starts or automatically retries a firmware session. Existing
startup/error presentation owns the result; successful preflight does not
present the camera as ready.


## Native review keys

Protect key and Delete key reuse the camera button style, capability list and
shared browser/AppKit bridge. Both require native EX controls and the explicit
card/playback profile. No Delete/Backspace shortcut is assigned. These are
external key presses: original firmware owns the confirmation displayed on the
camera screen, including Play to cancel and another Delete press to confirm.
The workbench reports queued input only. It never skips that screen, deletes
host files, retries a key automatically or claims a deletion has completed.
Keep the consequence text next to the keys; Stop remains available below them.


## Native command dials

Main/Sub dial minus and plus controls use the existing button styles and guarded
queue. Group each pair with its axis label and accessible names. On narrow
screens the complete dial group spans the control grid, with the axes side by
side. No new colors, dialogs, keyboard shortcuts or visual tokens are introduced.
The existing AppKit Camera menu calls the same `z8Workbench.turnDial` API and
receives an independent `dialsReady` capability through the same-origin bridge.
Host-peer and display-only sessions retain disabled controls and an inline reason.

Each admitted turn is one signed EX count, delivered through four separated
external pin phases. The backend serializes turns, buttons, modes and capture.
A delayed tick preserves minimum phase spacing; it never catches up by emitting
multiple edges at once. Shutdown returns an unfinished turn to its starting pin
levels without replaying it. Input delivery and firmware acceptance stay distinct.
