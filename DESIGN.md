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

## Motion

No decorative motion. Polling updates status and replaces the LCD image only when its content changes.
