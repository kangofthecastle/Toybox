# HUD Monitor Partitions (FancyZones-lite) — Design

> Approved 2026-07-15. Split any monitor into two halves — vertical (left/right) or
> horizontal (top/bottom) — with an adjustable ratio, and snap windows into the halves
> by Shift-dragging them. Pure stdlib (tkinter + ctypes), per the Toybox charter.

## What it does

- Each monitor has an independent partition state: `off | vertical | horizontal`,
  plus a split ratio (default 0.5, clamped to 0.15–0.85). Persisted in config,
  keyed by monitor device name (stable across reboots, unlike index).
- **Snap:** while a normal window is being dragged, a translucent click-through
  overlay appears on the monitor under the cursor showing the two zones of its
  active layout; the hovered zone highlights; releasing the mouse over a zone
  moves the window to fill that zone. No layout active on that monitor → no overlay.
  **Holding Shift while dragging opts out** (suppresses the overlay and the snap)
  so a window can still be placed freely; releasing Shift mid-drag resumes.
  (Amended 2026-07-16: originally Shift-to-activate; flipped to activate-on-drag
  with Shift-to-suppress at the user's request.)
- **Toggle:** the HUD gains a "partitions" row with one glyph per monitor
  (`▯` off / `◫` vertical / `⬓` horizontal). Left-click cycles off → vertical →
  horizontal. Right-click opens the divider editor.
- **Divider editor:** an interactive overlay on that monitor showing the divider line;
  drag it, release to commit the new ratio; Esc or clicking away cancels. Windows
  previously snapped this session re-snap to the new ratio (session-only memory;
  nothing persisted about individual windows).

## Architecture

New `zonekit/` package (logic), additions to `winkit/` (native glue), a small control
section in `hud.pyw` (UI + tick hook). The HUD process hosts everything; the tracker
poll only runs when at least one monitor has a layout active.

### winkit/monitors.py (new)
- `list_monitors() -> [Monitor]` via `EnumDisplayMonitors` + `GetMonitorInfoW`
  (`MONITORINFOEXW`): device name, full rect, **work rect** (excludes taskbar),
  primary flag. Coordinates are physical pixels (process is per-monitor-v2 DPI aware).
- `monitor_at(x, y)` via `MonitorFromPoint` (nearest fallback).
- All ctypes signatures explicit (`argtypes`/`restype`), per native-gotchas.

### winkit/window.py (additions)
- `foreground_window() -> hwnd`
- `window_rect(hwnd) -> (l, t, r, b)` — `GetWindowRect`.
- `frame_rect(hwnd)` — `DwmGetWindowAttribute(DWMWA_EXTENDED_FRAME_BOUNDS)`; used to
  compute the invisible-border insets so snapped windows visually fill the zone
  (raw SetWindowPos rects leave ~7 px gaps on Win10). Falls back to `window_rect`.
- `move_window(hwnd, x, y, w, h)` — restores if maximized (`IsZoomed` →
  `ShowWindow(SW_RESTORE)`), applies border compensation, `SetWindowPos` with
  `SWP_NOZORDER | SWP_NOACTIVATE`. Returns False on failure (e.g. elevated target);
  never raises.
- `is_snappable(hwnd)` — visible, not our own process's windows, not shell windows
  (class in `Progman`, `WorkerW`, `Shell_TrayWnd`, `#32768`...), not
  `WS_EX_TOOLWINDOW`, has a caption or is resizable.
- `window_class(hwnd)`, `is_window(hwnd)` helpers.

### zonekit/geometry.py (pure math — no Tk, no ctypes)
- `clamp_ratio(r)` → clamp to [0.15, 0.85].
- `zone_rects(work, layout, ratio) -> [rect, rect]` — vertical: left width =
  `round(w * ratio)`; horizontal: top height = `round(h * ratio)`. Exact tiling
  (second zone gets the remainder; no gaps/overlap).
- `zone_at(work, layout, ratio, x, y) -> 0 | 1 | None`.
- `divider_pos(work, layout, ratio)` / `ratio_from_point(work, layout, x, y)` —
  used by the divider editor.
- Handles negative-origin monitors (secondary left of primary).

### zonekit/tracker.py (drag-watch state machine — injectable inputs)
- `DragTracker(is_shift_down, is_lbutton_down, get_foreground, get_rect, is_snappable)`
  — all callables injected; unit tests feed synthetic sequences.
- Sampled every ~60 ms from the HUD tick. States: `IDLE → ARMED → DRAGGING → (drop)`.
  - ARMED: Shift + LButton down, snappable foreground window, rect recorded.
  - DRAGGING: same window's rect origin moved ≥ threshold (4 px) on a later sample.
  - Shift released mid-drag → cancel (overlay hides, drop suppressed).
  - LButton released while DRAGGING with Shift held → emit `("drop", hwnd, x, y)`
    using last cursor position; else silent return to IDLE.
- Emits simple events consumed by the HUD: `show`, `move`, `drop`, `cancel`.

### zonekit/overlay.py (Tk toplevels, built on winkit.window.apply_overlay_styles)
- `SnapOverlay` — borderless, topmost, `-alpha` translucent, **click-through**
  (`WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW`), covers one monitor's
  work area; canvas draws both zones (dim fill + border) and highlights the hovered
  one in the HUD accent cyan. Created on drag start, destroyed on drop/cancel.
- `DividerEditor` — same visual language but interactive (NO `WS_EX_TRANSPARENT`),
  `-alpha` translucent; drag the divider line, live-preview; commit on release,
  cancel on Esc/second click away. Calls back with the new ratio.
- Ex-styles applied after `update()` realizes the HWND; read-modify-write.

### hud.pyw (control surface + engine host)
- New partitions row under the volume band: label + one glyph per monitor, canvas
  items + hit-testing in `_on_release`, hover recolor — same pattern as the audio
  switcher. Height constant `ZONES_H` added to layout math.
- `_zones_tick()` chained via `root.after(60, ...)`, running only while any layout
  is active; drives `DragTracker`, shows/moves/hides `SnapOverlay`, performs the
  snap on drop (`move_window` to `zone_rects(...)[zone]`).
- Session map `self._zone_windows: {hwnd: (device, zone)}` — re-snap on ratio commit
  or layout change; entries pruned when `is_window()` fails or a snap fails.
- Monitor list refreshed lazily (on tick if stale > 5 s, and on demand) so
  plug/unplug is picked up without a restart.

### config.py
- New defaults under `hud`:
  ```json
  "zones": { "monitors": {} }
  ```
  where `monitors` maps device name → `{"layout": "off"|"v"|"h", "ratio": 0.5}`.
- Saved via scoped `config.update(CFG_PATH, {"hud": {"zones": ...}})` — safe with
  `_raw_merge` forward-compat semantics (older toys won't clobber it; PR #12).
- Unknown/missing monitors in config are ignored at runtime, never deleted.

## Data flow (snap path)

tick → tracker sample (Shift? LButton? foreground rect moved?) → on DRAGGING:
ensure overlay exists on `monitor_at(cursor)`, highlight `zone_at(cursor)` →
on drop: `move_window(hwnd, *zone_rect)` → record in `_zone_windows` → overlay down.

## Edge cases

- **DWM invisible borders:** compensate via `DWMWA_EXTENDED_FRAME_BOUNDS` delta so
  windows visually butt against the divider. Fallback: no compensation.
- **Elevated windows:** `SetWindowPos` fails → `move_window` returns False, skip
  silently.
- **Min/max size constraints:** window may not take the exact rect; accept the OS
  result (no retry loop).
- **Maximized window dragged:** Windows restores it as the drag starts; on drop we
  `SW_RESTORE` defensively anyway before positioning.
- **Monitor unplugged:** config entry retained; runtime ignores devices not present.
- **HUD/pet/clipboard windows:** excluded via own-PID check in `is_snappable`.
- **Overlay must never interfere:** click-through + no-activate; created hidden,
  styled, then shown (no taskbar flash), per native-gotchas §1.
- **Shift+drag inside apps that use Shift-drag themselves** (e.g. selection):
  tracker only arms when the *window rect is moving*, i.e. a real title-bar drag,
  so in-app Shift-drags never trigger the overlay.

## Scope cuts (v1)

No hotkeys; no >2 zones; no persisted per-app zone memory; no layout presets;
no multi-window cascade. The HUD glyph row is the only control surface.

## Testing (unittest, repo conventions)

- `tests/test_zone_geometry.py` — zone rects v/h, ratio clamp, exact tiling,
  negative-origin monitors, `zone_at` hit tests, divider math round-trip.
- `tests/test_zone_tracker.py` — synthetic input sequences: arm→drag→drop happy
  path; Shift release cancels; non-snappable window never arms; tiny jitter below
  threshold never drags; drop coordinates correct.
- `tests/test_hud_zones.py` — fake monitors: glyph cycling writes config (mocked
  `config.update`), re-snap map pruning, tick no-ops when all layouts off.
- Smoke: `test_smoke_hud.py` still passes (zones default off → zero behavior change).
- Native probes (manual/scripted on this machine): enumerate real monitors; move a
  scratch window into a computed zone rect and read back its frame rect.

## Risks / residuals

- Drag *feel* (overlay latency ~60–130 ms after drag start) — verify by hand.
- Border compensation values vary by theme/DPI — verified by probe on this machine,
  other machines may differ slightly (cosmetic only).
