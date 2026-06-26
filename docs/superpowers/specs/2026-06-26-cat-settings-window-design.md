# Cat Settings Window + Menu Declutter — Design

**Date:** 2026-06-26
**Status:** Proposed (design), pending user review → plan
**Runtime:** Python 3.12 stdlib only (tkinter + `tkinter.ttk` + ctypes + winreg + winsound). Extends `winkit`/`petkit`.

## Overview

The cat grew to ~11 abilities, surfaced through a single right-click menu that mixed *actions* (Focus, Add reminder…) with nine on/off *checkboxes*, while its most useful tools had invisible triggers. Two passive abilities (clipboard helper, app-focus tracker) were already removed. This change makes the three genuinely interactive tools — the **focus timer**, **reminders**, and **window pin** — properly usable and configurable, and declutters the right-click menu by moving every on/off toggle into a dedicated **Settings window**.

The ambient behaviors (base cat: glow/hop/eyes/persona/drag; petting & purr; box catnap; welcome-back greeter; break nudges) need no instruction — they just happen — so they get a simple on/off toggle in the window and nothing more.

Hard requirement, unchanged: **super lightweight, pure stdlib, no pip.** The Settings window is built on demand and reused (singleton); the per-frame tick loop is untouched except for one gated, low-rate top-most re-assert while windows are pinned.

## Goals / Non-goals

**Goals:**
- A slim default right-click menu focused on *doing* things, with all on/off toggles removed from it.
- A dedicated tabbed Settings window (`Focus | Reminders | Pin | More`) that hosts real config controls menus can't: number fields, an editable reminders list, a pinned-windows list.
- Focus timer: set focus/break minutes from the GUI; start/pause/stop with a live countdown.
- Reminders: structured add (message + `in N [unit]` / `at HH:MM`) plus a managed list of pending reminders with per-item remove.
- Pin: pin/unpin the **window under the cat** via the right-click menu (no hotkey); the cat **always stays above** pinned windows.

**Non-goals (explicitly cut):**
- The global pin **hotkey** (`Ctrl+Shift+P`) and the `pin_hotkey` config key — removed; pinning is cat-driven now.
- No new config keys, no new abilities, no theming/skins, no changes to the ambient behaviors' logic.
- No re-introduction of the removed clipboard helper / app-focus tracker.

## The default right-click menu (decluttered)

Built in `pet.pyw` `_on_right_click`. The nine→seven toggle checkbuttons are **removed** from here.

```
🐱 Cat                         (disabled header)
──────────────
▶ Start Focus (25m)            ← when running: ⏸ Pause MM:SS · ▶ Resume · ■ Stop
⏰ Reminders…                  → opens Settings ▸ Reminders
📌 Pin this window             → toggles pin on the window under the cat;
                                 label reads "Unpin this window" when it is pinned
──────────────
⤵ Drop N file(s) → clipboard   ← only while carrying files (existing behavior)
  Let go
📌 Unpin all (N)               ← only while ≥1 window is pinned
──────────────
⚙ Settings…                   → opens Settings ▸ (default Focus tab)
Hide cat
```

The dynamic Focus block (Start vs Pause/Resume/Stop) and the contextual Catch-&-Carry / Unpin-all items keep today's behavior. The old `_add_reminder_dialog` and the in-menu reminder cancel submenu are removed (their job moves to the Reminders tab).

## The Settings window (`petkit/settings.py`, new)

A normal titled, movable, closable `Toplevel` (NOT the transparent color-key overlay). Tabs via `ttk.Notebook`. Owned by `Cat` as a **singleton**: `Cat._open_settings(tab=None)` creates it on first use or raises + selects `tab` if already open; closing it (window ✕ / `WM_DELETE_WINDOW`) destroys it and clears the reference so a later open recreates it. The window reads/writes the live `cfg["pet"]` dict and calls back into `Cat` for actions; `Cat` persists via `config.save` and applies changes immediately (reusing `_apply_pin_enabled`, etc.).

`SettingsWindow` is GUI glue (no pure-logic algorithms of its own); the testable logic it depends on lives in `petkit/reminders.py` and `winkit/window.py`. It is covered by a GUI smoke test (open → build all tabs → refresh → close, no crash), like `petkit/bubble.py`.

### Focus tab
- `Focus [25] min`  `Break [5] min` integer entry fields + **Save** → writes `cfg["pet"]["focus_min"]` / `["break_min"]` (validated to positive ints; bad input reverts to the saved value) and updates the `Pomodoro` object's durations (applied on the next Start).
- `▶ Start · ⏸ Pause/▶ Resume · ■ Stop` buttons calling the existing `Cat._start_focus/_pause_focus/_resume_focus/_stop_focus`.
- A live `MM:SS` remaining label, refreshed by the window's own lightweight `after()` loop **only while the window is open**.

### Reminders tab
- Structured add: `Message [____]`, radio `(•) in [N] [min ▾ / hours]` vs `( ) at [HH:MM]`, **Add**.
- **Add** computes the due epoch via a pure helper (below) and calls `Cat.reminders.add(message, due)`; empty message → "Reminder". Invalid time fields → a brief inline error, no add.
- Pending list: one row per `Reminders.pending()` item — `• <text>   <when>   ✕` — `<when>` from `format_due`; `✕` calls `Reminders.remove(text, due)` (precise, not cancel-by-text). The list refreshes after add/remove.
- Top of tab: `☑ Enable reminders` bound to `cfg["pet"]["reminders"]`.

### Pin tab
- `☑ Enable pin` bound to `cfg["pet"]["pin"]`. When off, the menu's Pin item is hidden and pins are released (existing `_apply_pin_enabled` semantics, minus the hotkey poller).
- **Pin the window under me** button — mirrors the menu action (`Cat._pin_under_cat`).
- Pinned-windows list: one row per `PinSet.pinned()` hwnd — `• <window_title>   ✕` (`window.window_title(hwnd)`); `✕` unpins that one (`PinSet.toggle(hwnd)`); **Unpin all** calls `PinSet.unpin_all`. Refreshes on change.
- No hotkey field (the hotkey is gone).

### More tab
- The remaining ambient on/off toggles, each a checkbox bound to its `cfg["pet"]` key, applied + saved on change:
  Petting & purr (`petting`), Box catnap (`catnap`), Welcome-back greeting (`greeter`), Break nudges (`nudges`), Catch & carry files (`carry`).

## Pin redesign (cat-driven, cat stays on top)

**Trigger.** Position the cat over the target window; right-click ▸ **Pin this window**. The target is the window directly beneath the cat. No hotkey.

**Finding the window under the cat — `winkit/window.window_below(hwnd)`.** Compute `hwnd`'s center from `GetWindowRect`; temporarily OR `WS_EX_TRANSPARENT` into the cat's ex-style (so hit-testing passes through it), `WindowFromPoint(center)` → `GetAncestor(GA_ROOT)`, then restore the ex-style in a `finally`. Returns the root hwnd beneath, or `0` for none / the desktop / the cat itself. This is the only reliable way to name the window under a hit-testable top-most overlay.

**Keeping the cat above pinned windows (fixes the current bug).** Today, pinning sets the target `HWND_TOPMOST`, which lands it *above* the cat. New behavior:
1. After a successful pin, immediately re-raise the cat: `window.set_topmost(self.hwnd, True)` (re-inserts the cat at the top of the top-most band; `SWP_NOACTIVATE`, so no focus theft).
2. While `PinSet.pinned()` is non-empty, `Cat.tick` re-asserts the cat's top-most at a **low rate (~1×/sec, gated)** — `if pinned and now >= self._next_topmost: self._next_topmost = now + 1.0; window.set_topmost(self.hwnd, True)` — so activating a pinned window can't bury the cat.

Net z-order guarantee: **cat > pinned window(s) > normal windows.**

**Menu state.** When building the menu, `Cat` resolves `target = window.window_below(self.hwnd)` once and labels the item **Unpin this window** if `PinSet.is_pinned(target)` else **Pin this window**; if `target == 0` the item still shows "Pin this window" and is a no-op with a brief "no window here" bubble.

## Components & files

```
petkit/settings.py     # NEW: SettingsWindow (Toplevel + ttk.Notebook; 4 tabs); GUI glue
petkit/reminders.py    # EXTEND: pure due_from_fields()/format_due(); Reminders.remove(text, due)
winkit/window.py       # EXTEND: window_below(hwnd), window_title(hwnd)
pet.pyw                # slim menu; _open_settings(tab); singleton window mgmt;
                       #   _pin_under_cat(); low-rate cat top-most re-assert;
                       #   remove HotkeyPoller pin wiring, _add_reminder_dialog, cancel submenu
config.py              # remove the now-unused "pin_hotkey" key (keep "pin")
```

`winkit` stays the reusable native layer; `petkit` holds pet feature logic + its GUI pieces (precedent: `petkit/bubble.py`). `winkit.input.HotkeyPoller` itself stays (the Clipboard toy uses it); only the pet stops using it.

### New/changed function signatures
- `petkit/reminders.py`
  - `due_from_fields(mode, amount, unit, hh, mm, now_epoch) -> int | None` — `mode="in"` uses `amount`+`unit` (`"min"|"hours"`, with seconds available internally); `mode="at"` uses `hh`,`mm` (24h), rolling to tomorrow if already past, mirroring `_parse_clock`. Returns an epoch int or `None` on invalid input.
  - `format_due(due_epoch, now_epoch) -> str` — e.g. `"4:12pm"`; prefixes `"tomorrow "` when the due day differs from `now`'s day.
  - `Reminders.remove(text, due) -> None` — deletes the single item matching both `text` and `due` (atomic save), unlike `cancel(text)` which removes all matches.
- `winkit/window.py`
  - `window_below(hwnd) -> int` — root window beneath `hwnd` at its center (see Pin redesign); `0` if none.
  - `window_title(hwnd) -> str` — `GetWindowTextW`; `""` on failure. Truncation for display is the caller's job.

## Data / persistence

- `config.json` `"pet"`: **no new keys.** Reuses `focus_min`, `break_min`, `reminders`, `pin`, `petting`, `catnap`, `greeter`, `nudges`, `carry`. **Removes** `pin_hotkey`. `config._deep_merge` already ignores unknown keys, so an old config.json carrying `pin_hotkey` loads cleanly (the stale key is dropped on next save).
- `reminders.json`: unchanged shape (`[{text, due}]`, atomic write).

## Testing strategy

**Pure logic (TDD, cross-platform):**
- `due_from_fields`: `in 20 min` → `now+1200`; `in 2 hours` → `now+7200`; `at HH:MM` later today vs already-past (→ +1 day); invalid (`hh=99`) → `None`.
- `format_due`: same-day time format; tomorrow prefix; stable for a fixed injected `now`.
- `Reminders.remove`: removes exactly one of two same-text different-due items; persists; no-op when absent.

**Win32 integration smoke (Windows-only, like `test_winkit_system.py`):**
- `window_below(hidden-cat-hwnd)` returns an int without raising and restores the cat's ex-style (assert `WS_EX_TRANSPARENT` not left set).
- `window_title(GetForegroundWindow())` returns a `str`.

**GUI smoke (hidden Tk root / `TOYBOX_SMOKE`):**
- Open `SettingsWindow`, build all four tabs, call its refresh paths (reminders list, pinned list, focus remaining), then close — no exception; reopening recreates cleanly.
- `pet.pyw` launches and exits clean (existing `test_smoke_pet`), now exercising the slimmed menu construction and the pin/top-most paths via `Cat.tick`.
- Menu-structure assertion: the default menu contains a `Settings…` command and **no** toggle checkbuttons.

## Lightweight discipline

- Settings window: created only on open, destroyed on close; its `MM:SS` refresh `after()` loop runs only while open.
- Pin top-most re-assert: gated to `PinSet.pinned()` non-empty and rate-limited to ~1×/sec; `SWP_NOACTIVATE` so it never steals focus or flickers.
- `window_below` runs only on a pin/menu action, not per frame; it restores the cat's ex-style in a `finally`.
- Per-frame tick cost is otherwise unchanged.

## Risks & mitigations

- **`window_below` leaves the cat click-through** if an exception interrupts the toggle → always restore in `finally`; smoke-assert the bit is clear afterward.
- **Top-most fight with a fullscreen app** → re-assert is gated (only while pins exist) and low-rate; acceptable for a deliberately always-visible pet. If it ever annoys, the rate/gate is one constant to tune.
- **ttk look differs** from the app's plain-tk widgets → acceptable for a standalone config window; it stays unstyled/native.
- **Singleton lifecycle leaks** (multiple Toplevels / callbacks after destroy) → one owned reference cleared on `WM_DELETE_WINDOW`; all `after()`/refresh guarded against `TclError` like `bubble.py`.
- **Stale `pin_hotkey` in user configs** → harmless; `_deep_merge` ignores unknown keys and it's dropped on next save.
