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
message. AppKit intersects that set with the four known commands and also
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
