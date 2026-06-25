# Floating Clipboard — Design

**Date:** 2026-06-24
**Status:** Approved (design), proceeding to plan
**Runtime:** Python 3.12 stdlib only (tkinter + ctypes + winreg). Reuses the `winkit` package.

## Overview

Replace the current hidden-controller + centered-picker clipboard with a **floating, static clipboard icon** that opens a real two-column clipboard-manager **panel**. This is a separate widget from the music-reactive pet (the pet is unchanged). It gives the user a discoverable, clickable "functional little guy" and a much richer clipboard UX.

## Goals / Non-goals

**Goals:** A draggable always-on-top clipboard icon; click → two-column (All / Favorites) panel; favorites that persist; multi-select + shift-select bulk delete in All; click-to-copy; search; right-click utility menu. Stay pure-stdlib and lightweight. Privacy: only favorited items are written to disk.

**Non-goals (explicitly deferred):** Cloud / cross-device sync. A "Short" column/filter. Inline edit, manual "+" add, and "share" from the screenshot. Multi-select in the Favorites column (selection is an *All*-only feature).

## Components & files

```
clipboard.pyw      # rewritten: icon window + panel + capture loop + hotkey + menu
clip_store.py      # NEW pure-logic model: recent (in-memory) + favorites (persisted)
timeago.py         # NEW pure helper: seconds-elapsed -> "just now" / "4m" / "4h" / "3d"
config.py          # extend the "clipboard" section (icon x/y, capture flag, max_items)
favorites.json     # generated at runtime; persisted favorites only
winkit/*           # reused unchanged (window styles, input, startup guard/mutex)
```

`clip_history.py` (the old plain ring buffer) is superseded by `clip_store.py`; it can remain for its existing tests but `clipboard.pyw` will use `clip_store`.

## Data model (`clip_store.py`, pure logic — TDD)

Two ordered lists of entries; each entry is `{"text": str, "time": float}` (epoch seconds).

- **`recent`** — in-memory, newest-first, capped at `max_recent` (default 30).
- **`favorites`** — persisted to `favorites.json`, newest-favorited-first, uncapped.
- An item lives in **exactly one** list (texts are unique across both).

`ClipStore(max_recent, favorites_path)` API:
- `add(text, now)` → if `text` is whitespace-only: ignore. If it matches an existing **favorite**: ignore (already kept). If it matches an existing **recent**: move it to front (refresh time). Else: insert at front of `recent`, evict past `max_recent`. Returns bool (changed).
- `recent()` / `favorites()` → copies of the entry lists (newest-first).
- `favorite(text)` → remove from `recent`, insert at front of `favorites`, save. No-op if not in recent.
- `unfavorite(text)` → remove from `favorites`, insert at front of `recent` (cap applies), save. No-op if not in favorites.
- `delete(text)` → remove from whichever list holds it; save if it was a favorite.
- `delete_many(texts)` → remove each from `recent` (bulk delete is All-only).
- `clear_recent()` → empty `recent`; favorites untouched.
- Persistence: load favorites from `favorites_path` on construction (missing/corrupt → empty list, no crash); `save` writes atomically (temp + replace) after any favorites mutation.

`timeago.py`: `format_ago(elapsed_seconds)` → `"just now"` (<60s), `"Nm"` (<60m), `"Nh"` (<24h), `"Nd"` (else). Pure, TDD.

## The icon (`clipboard.pyw`)

A small (~40px) borderless, always-on-top, shaped window near a screen corner (config `clipboard.x/y`, else default). Drawn procedurally on a `KEY_COLOR` canvas in the pet's teal palette: a rounded clipboard body with a clip tab — **static, no animation**. Uses `winkit.window.apply_overlay_styles(clickthrough=False)` so the icon's pixels are clickable while the transparent margin passes clicks through; `no_activate=True` so it doesn't steal focus.

Interactions:
- **Left-click (no drag)** → toggle the panel open beside the icon.
- **Left-drag** → move the icon; persist `x/y` to config (click-vs-drag distinguished by a small motion threshold, as the pet does).
- **Right-click** → utility menu (`tk.Menu`): Pause/Resume capture · Clear history · Run at login (✓) · Hide icon · Quit.

## The panel (`tk.Toplevel`)

Opens adjacent to the icon, clamped on-screen; borderless, always-on-top, dark theme matching the existing picker. Layout:

- **Header:** a capture on/off toggle (reflects `clipboard.capture`), a Search entry (filters both columns, case-insensitive), and a close ✕.
- **Body — two scrollable columns** (each a Canvas+inner Frame scroll region):
  - **ALL** rows: `[checkbox] [time-ago] [text (one line, truncated)] [char count] [☆] [✕]`.
  - **FAVORITES** rows: `[time-ago] [text] [char count] [★] [✕]` (no checkbox).
- **Footer:** a **"Remove selected (N)"** button, shown only when ≥1 All-checkbox is checked.

Behaviors:
- **Click a row's text** → `clipboard_clear` + `clipboard_append(text)`, then close the panel. (Selecting an item copies it.)
- **☆ in All** → `store.favorite(text)`, refresh both columns (item moves to Favorites). **★ in Favorites** → `store.unfavorite(text)`, item returns to top of All.
- **✕** → delete that single row from its column; refresh.
- **All checkboxes** → multi-select; **Shift-click** selects the inclusive range between the last-toggled checkbox (anchor) and the clicked one. **Remove selected** calls `store.delete_many(selected_texts)` and refreshes.
- **Search** re-renders both columns filtered by substring (case-insensitive).
- **Close:** ✕ button, Esc, or focus-out (click-away). Panel is destroyed on close (rebuilt fresh on next open) so it always reflects current state.

## Capture & hotkey

A `~250 ms` `after()` loop polls `winkit.input.clipboard_sequence()`; on change, if capture is enabled, reads `clipboard_get()` (guard `TclError` for non-text) and `store.add(text, time.time())`. Seeds from the current clipboard at startup (carried over from the existing fix). `Ctrl+Shift+V` (via `winkit.input.HotkeyPoller`) opens the panel — same as clicking the icon.

## Config additions

```jsonc
"clipboard": { "max_items": 30, "hotkey": ["ctrl","shift","V"],
               "x": null, "y": null, "capture": true }
```
Favorites are NOT in config; they live in `favorites.json`.

## Error handling

`clipboard.pyw` keeps the shared skeleton (guard_streams first, single-instance guard, try/except → `toybox.log`). Corrupt `favorites.json` → empty favorites (no crash). All Win32 via `winkit`. A failed favorites save is swallowed (never crashes the UI).

## Testing

- **Unit (TDD):** `clip_store` — add/dedup/cap, favorite/unfavorite move semantics + ordering, delete/delete_many, clear_recent, favorites load/save round-trip + corrupt fallback, uniqueness across lists. `timeago.format_ago` — each bucket boundary.
- **GUI:** smoke-launch (`TOYBOX_SMOKE`) of `clipboard.pyw` exits clean; visual verification via screenshot (icon renders; panel opens with two columns; favoriting moves an item). Shift-select range logic is unit-testable if extracted as a pure helper (anchor+index → set of indices).

## Implementation order

1. `timeago.py` + `clip_store.py` with full unit tests.
2. Extend `config.DEFAULTS["clipboard"]`.
3. `clipboard.pyw`: icon window (draw + drag + persist + menu).
4. `clipboard.pyw`: panel (two columns, rows, copy-on-click, star moves, search).
5. `clipboard.pyw`: checkbox multi-select + shift-select + bulk remove.
6. Capture loop + hotkey wiring; smoke + visual verify.
