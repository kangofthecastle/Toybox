# Toybox — Lightweight Windows Desktop Toys

**Date:** 2026-06-24
**Status:** Approved (design), pending spec review
**Runtime:** Python 3.12 (`py` launcher / `pythonw.exe`), **standard library only** — `tkinter`, `ctypes`, `winreg`, `unittest`. Zero pip installs.

## Overview

A small collection ("Toybox") of standalone, super-lightweight Windows desktop toys, plus one system-tray launcher that starts/stops them and toggles run-at-startup. Each toy is an independent `.pyw` script runnable on its own; the launcher is optional convenience.

Three toys:
1. **System Monitor HUD** — translucent always-on-top overlay: live CPU %, RAM %, clock, sparklines.
2. **Clipboard History** — invisible helper; captures copied text into an in-memory ring buffer; a global hotkey pops a picker to re-copy past entries.
3. **Music-Reactive Pet** — a small transparent, click-through creature that dances/reacts to whatever audio is playing through the system, polled via the Windows audio peak meter.

## Goals / Non-goals

**Goals:** Zero-install (stdlib only). Super lightweight (near-zero idle CPU, tiny RAM). Each toy isolated and independently runnable. No network, no telemetry, no disk-persisted clipboard.

**Non-goals (YAGNI):** No screensaver (dropped). No audio *capture*/recording or FFT spectrum — amplitude envelope is enough. No multi-monitor management beyond "remember position." No settings GUI — `config.json` is hand-editable; common toggles live in the tray menu.

## Lightweight performance budget

This is a hard requirement, not a nice-to-have.

- **HUD:** metric sample + redraw at **1 Hz**. Sparkline keeps a fixed ring (~60 points). Target: negligible CPU, < 25 MB RAM.
- **Clipboard:** clipboard-change check via `GetClipboardSequenceNumber` (a single cheap int read) at **~4 Hz**; hotkey check via `GetAsyncKeyState` at **~15 Hz**. No work unless something changed. Picker window created on demand, destroyed on dismiss.
- **Pet:** audio peak poll + animation tick at **30 Hz while audio is active**; when audio has been silent for ~2 s, **drop to ~8 Hz** idle. A peak poll is a sub-microsecond COM float read. Canvas redraw only when the frame actually changes.
- **Launcher:** pure Win32 message loop, idle (event-driven), one tray icon.

## Architecture

```
C:\Users\Warren\Toybox\
├─ toybox.pyw       # tray launcher (the only Win32 message loop + tray icon)
├─ win32.py         # shared ctypes helpers (the only place ctypes lives)
├─ hud.pyw          # System Monitor HUD            (tkinter)
├─ clipboard.pyw    # Clipboard history + hotkey    (tkinter)
├─ pet.pyw          # Music-reactive pet            (tkinter)
├─ config.py        # load/save config.json with defaults
├─ config.json      # generated at first run
├─ toybox.log       # crash log (one line per crash)
└─ tests\           # unittest for pure-logic modules
```

**Single-message-loop rule.** Mixing a manual ctypes Win32 message loop with tkinter's `mainloop` in one process is fragile. Therefore the **launcher** is the only process that owns a Win32 message loop and the single tray icon. Every toy is an ordinary tkinter process (own `mainloop`), spawned/killed by the launcher as a child process. Toys are independent: a crash in one cannot affect another or the launcher.

**No system-wide hotkey registration.** The clipboard hotkey is detected by polling `GetAsyncKeyState` on a tkinter `after()` timer — no `RegisterHotKey`, no message loop needed inside a tkinter process. Simple and robust.

### `win32.py` — shared ctypes helpers

The single home for all native code, so each toy stays clean and the tricky parts are tested/reviewed once:

- **Window styling:** make a tkinter window always-on-top, layered/translucent, and (for the pet) click-through (`WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_TOOLWINDOW` via `GetWindowLong`/`SetWindowLong`). Hide from alt-tab.
- **Metrics:** `cpu_percent()` from `GetSystemTimes` deltas (idle/kernel/user); `ram_percent()` from `GlobalMemoryStatusEx`.
- **Clipboard:** `clipboard_sequence()` (`GetClipboardSequenceNumber`) to detect changes cheaply. (Reading/setting clipboard *text* is done in `clipboard.pyw` via its own tkinter root's `clipboard_get`/`clipboard_clear`/`clipboard_append` — kept out of the non-tkinter `win32.py`.)
- **Keys:** `key_down(vk)` wrapping `GetAsyncKeyState`; helper to test a modifier+key combo.
- **Audio:** `AudioPeakMeter` class wrapping the validated COM chain — `CoCreateInstance(MMDeviceEnumerator)` → `GetDefaultAudioEndpoint(eRender, eConsole)` → `Activate(IAudioMeterInformation)` → `GetPeakValue()` returning a float 0.0–1.0. Re-acquires the endpoint if the default device changes (HRESULT error → rebuild). **Validated by spike on 2026-06-24.**
- **Startup:** `set_run_at_startup(name, target, enabled)` / `is_run_at_startup(name)` via `winreg` `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, value = `pythonw.exe "<path>\<toy>.pyw"`.

## The toys

### 1. System Monitor HUD (`hud.pyw`)

Borderless (`overrideredirect`), semi-transparent (`-alpha`), always-on-top tkinter window. A canvas shows CPU % and RAM % as numbers plus scrolling sparklines, and a clock (HH:MM:SS). Left-drag moves it (position saved to config). Right-click menu: opacity presets, "lock position," close. Reads metrics from `win32.py` at 1 Hz.

### 2. Clipboard History (`clipboard.pyw`)

Hidden tkinter root (withdrawn). Two timers:
- **~4 Hz:** if `clipboard_sequence()` changed, read current clipboard text; if non-empty and different from the newest entry, push onto a ring buffer (default cap **20**, configurable). Move-to-front on duplicate. In-memory only — never written to disk.
- **~15 Hz:** if the hotkey combo (default **Ctrl+Shift+V**) is freshly pressed (edge-detected), show the picker.

Picker: a centered `Toplevel` listbox of entries (newest first, each truncated to one line). Arrow keys / type-to-filter; **Enter** or click sets that entry as the clipboard contents and closes; **Esc** closes. The picker is created on demand and destroyed on close (no idle cost).

### 3. Music-Reactive Pet (`pet.pyw`)

Small transparent, click-through, always-on-top tkinter window sitting near the bottom of the screen. A canvas-drawn blob creature (cute, abstract — eyes + body). Click-through via `WS_EX_TRANSPARENT` so it never intercepts clicks; `-transparentcolor` makes the window background invisible so only the creature shows.

**Audio reactivity (the "intelligent" part):** each tick, read the system output peak (0.0–1.0) from `win32.py`'s `AudioPeakMeter`. Derive:
- **Loudness envelope:** smoothed peak → drives bob height / squash-stretch / a subtle color shift. Louder = bigger, bouncier.
- **Beat/onset detection:** keep a moving average of recent peaks; flag a beat when `peak > avg * sensitivity` AND `peak > floor` AND a refractory interval (~150 ms) has elapsed since the last beat. On a beat the pet does a discrete reaction (hop / spin / blink).
- **State machine:**
  - *Silent* (envelope ≈ 0 for ~2 s): pet idles — gentle breathing, occasional blink, may "nap"; loop throttles to ~8 Hz.
  - *Quiet music:* gentle sway in time with the envelope.
  - *Loud / beaty:* dances — bob amplitude scales with loudness, hops on detected beats.

All tunables (`sensitivity`, `floor`, smoothing, idle-fps, position) live in `config.json`.

## Configuration (`config.json`)

Single JSON file, hand-editable, created with defaults on first run. Schema (illustrative):

```json
{
  "hud":   { "x": 40, "y": 40, "alpha": 0.85, "locked": false },
  "clipboard": { "max_items": 20, "hotkey": ["ctrl","shift","V"] },
  "pet":   { "x": null, "y": null, "sensitivity": 1.6, "floor": 0.02,
             "smoothing": 0.4, "idle_fps": 8, "active_fps": 30 },
  "startup": { "hud": false, "clipboard": false, "pet": false }
}
```

`config.py` loads with per-key fallback to defaults (missing/corrupt file → defaults, no crash) and saves atomically (write temp, replace).

## Error handling

Each toy's `main()` is wrapped: on unhandled exception, append one timestamped line to `toybox.log` and exit non-zero. Because toys are separate processes, one crashing never affects the others or the launcher. `win32.py` checks HRESULTs/return codes and raises readable `OSError`s. The pet's audio meter self-heals: on a COM error it tries to rebuild the endpoint a few times, then falls back to "silent" behavior (so the pet still lives if audio is unavailable). Corrupt config → defaults.

## Testing strategy

GUI/visual behavior: manual smoke test (launch each `.pyw`, observe). Pure logic is unit-tested with stdlib `unittest`, built test-first:

- **Clipboard ring buffer:** cap enforcement, dedup/move-to-front, ordering, re-copy selection. (Pure data structure, no Win32.)
- **Beat detector:** feed synthetic peak sequences (silence, steady tone, pulse train) → assert beat flags fire on onsets, respect refractory + floor, and not on silence.
- **CPU% computation:** feed two synthetic `GetSystemTimes` snapshots → assert the percentage math.
- **Config:** load defaults when absent, per-key fallback on partial/corrupt JSON, save→load round-trip.
- **Startup registry:** write→read→clear round-trip against a temp registry value (or an injected backend) to avoid clobbering the real `Run` key in tests.

Win32 wrappers that can't be unit-tested are isolated in `win32.py` and exercised by manual launch.

## Implementation order (for the plan)

1. `win32.py` + `config.py` (foundations) with their unit-testable logic.
2. Clipboard History (most self-contained, high daily value).
3. System Monitor HUD.
4. Music-Reactive Pet (depends on the validated audio meter).
5. Tray launcher (`toybox.pyw`) tying them together + startup toggles.
