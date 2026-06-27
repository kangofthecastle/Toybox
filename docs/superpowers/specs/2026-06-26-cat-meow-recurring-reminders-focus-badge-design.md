# Cat: Meow Chime + Recurring Reminders + Focus Badge — Design

**Date:** 2026-06-26
**Status:** Approved (design)
**Runtime:** Python 3.12 stdlib only (tkinter + ctypes + winsound + `wave`). Extends `petkit/`. No pip, ever.

## Overview

Three independent quality-of-life tweaks to the Cat pet, sharing one spec/plan
because each is small:

1. **Meow chime** — replace the Windows "Asterisk" system sound with a real cat
   *meow* so the cat's alerts are unmistakably the cat, not a Windows
   notification.
2. **Recurring reminders** — each reminder is either one-time (today's behavior)
   or **daily**; a daily reminder reschedules itself instead of being deleted
   when it fires.
3. **Focus badge** — a small always-on-top countdown floats just above the cat
   while a focus/break/paused timer is running.

Each ships as its own working, tested increment. The winkit/petkit split and the
"pure logic takes an injected clock and is unit-tested" discipline are preserved.

## Component 1 — Meow chime

**Where:** `petkit/bubble.py` (the speech bubble owns the chime); a new bundled
asset `assets/meow.wav`.

Today `bubble.say(..., chime=True)` plays `winsound.MessageBeep(MB_ICONASTERISK)`
— a Windows *system* sound. All of `MessageBeep`'s aliases are system sounds, so
the only fix is to play our own audio.

- Bundle a **freely-licensed (CC0 / public-domain) short cat meow** as
  `assets/meow.wav`. It MUST be a PCM WAV — the only format `winsound` plays.
  The file is validated at build time and by a test (readable by the stdlib
  `wave` module, `comptype == 'NONE'`). If no suitable online WAV can be
  obtained, a short meow-like tone is **synthesized** into `assets/meow.wav` with
  the stdlib `wave` module so the feature still ships; the source/license is
  noted in the asset task. CC0 requires no attribution; if a chosen source needs
  it, record it in `README.md`.
- `bubble.py` resolves the path relative to the package:
  `_MEOW = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "meow.wav"))`.
- Chime becomes:
  `winsound.PlaySound(_MEOW, SND_FILENAME | SND_ASYNC | SND_NODEFAULT)`.
  - `SND_ASYNC` → non-blocking (no animation hitch on the ~8 fps tick).
  - `SND_NODEFAULT` → if the file is missing/unreadable, **silence** — never the
    Windows default beep.
  - Wrapped in `try/except` (unchanged resilience).
- The 5 existing alerts keep `chime=True` and now meow: welcome-back greeting,
  focus-done, break-done, due reminders, stretch nudges.

**Error handling:** missing/invalid file → silent (SND_NODEFAULT + try/except).
No change to callers.

## Component 2 — Recurring reminders

**Where:** `petkit/reminders.py` (data model + firing) and
`petkit/settings.py` (Reminders tab UI).

A reminder item gains a `repeat` field: `"none"` (one-time) or `"daily"`.

**Data model / store (`reminders.py`):**
- Item shape becomes `{"text": str, "due": int, "repeat": "none"|"daily"}`.
- `_load` reads `repeat`, defaulting to `"none"` and coercing any value not in
  `{"none","daily"}` to `"none"`. **Back-compat:** existing `reminders.json`
  entries without a `repeat` key load as one-time.
- `add(self, text, due_epoch, repeat="none")` — stores `repeat` (coerced to
  `"none"` if not `"daily"`). Default keeps all current callers one-time.
- `due(self, now_epoch)` — for each item with `due <= now_epoch`:
  - `repeat == "daily"` → advance its `due` to the next future occurrence and
    keep it pending.
  - else → remove it (today's behavior).
  Saves once if anything changed; returns the fired texts (sorted by the due
  that fired), so the cat still bubbles+meows each one exactly once per fire.
- `pending()` already returns dict copies; they now include `repeat`.
- New **pure** helper `advance_daily(due, now) -> int` — smallest
  `due + 86400*k` strictly greater than `now` (`k >= 1`). If the app was off for
  days, a daily reminder jumps straight to the next future slot — it fires once,
  not once per missed day.

**UI (`settings.py` Reminders tab):**
- A **one-time / daily** control when adding (a "Repeat daily" checkbutton).
  On Add, pass `repeat="daily" if checked else "none"` to `reminders.add`.
- The pending list marks recurring items with a `↻` prefix (e.g.
  `↻ • water   daily 9:00am`); the per-row `✕` delete works on both kinds
  (`Reminders.remove` already matches text+due).

**Data flow:** `pet.pyw` `tick` already fires reminders via
`self.reminders.due(time.time())`; recurrence lives entirely inside `due()`, so
**pet.pyw needs no change** for firing.

## Component 3 — Focus badge

**Where:** new `petkit/timerbadge.py`; wired into `pet.pyw`.

A small always-on-top badge floats just above the cat's head while a timer runs,
showing the live countdown. It mirrors the bubble's window technique (its own
transparent `Toplevel`, `overrideredirect`, `-topmost`, `-transparentcolor`,
rounded-rect + text on a `Canvas`) and reuses `bubble.bubble_xy` for placement,
so it sits exactly where bubbles do. Transient meow bubbles still pop over it
briefly (they are topmost and short-lived).

- **Pure** `badge_text(state, remaining_s) -> str`:
  - `"focus"` → `"🎯 MM:SS"`, `"break"` → `"☕ MM:SS"`, `"paused"` → `"⏸ MM:SS"`,
    anything else → `""`. `remaining_s` clamped to `>= 0`; `MM:SS` via
    `divmod(int(remaining), 60)`. Unit-tested (no Tk).
- `class TimerBadge`: `__init__(self, root, head_offset=0)` builds one withdrawn
  Toplevel; `show(self, text)` renders+positions+deiconifies (no-ops on empty
  text → hide); `hide(self)` withdraws; `destroy(self)`. Every Tk call guarded
  against `tk.TclError` like `bubble.py`.
- **Wiring in `pet.pyw`:**
  - `__init__`: `self.timerbadge = timerbadge.TimerBadge(root, head_offset=head_y)`
    (reuse the existing `head_y`).
  - `tick` (right after the pomodoro `update`/done-event block):
    ```
    st = self.pomodoro.state
    if st in ("focus", "break", "paused"):
        self.timerbadge.show(timerbadge.badge_text(st, self.pomodoro.remaining(now)))
    else:
        self.timerbadge.hide()
    ```
  - `close`: guarded `self.timerbadge.destroy()`.
- **fps:** unchanged. Seconds-resolution only needs ≥1 fps; the cat already runs
  at idle/nap fps (≥ that) during a timer, so the badge ticks fine without
  pinning active fps.

## Testing strategy

- **Recurring reminders (unit, pure):** `advance_daily` (next future slot;
  exact-multiple edge; already-future is unchanged); `due()` reschedules a daily
  item and keeps it pending while removing a one-time; far-past daily fires once
  and lands in the future; `_load` back-compat (old item → `repeat="none"`,
  bad `repeat` → `"none"`); `pending()` includes `repeat`. (`tests/test_reminders.py`)
- **badge_text (unit, pure):** focus/break/paused/idle formats; clamp negative;
  MM:SS rollover. (`tests/test_timerbadge.py`)
- **TimerBadge (Windows-only GUI smoke):** build, `show`/`hide`/`destroy` on a
  real Tk root without raising. (`tests/test_timerbadge.py`)
- **Meow asset + chime (Windows-only smoke):** `assets/meow.wav` exists and is a
  PCM WAV (`wave.open` succeeds, `getcomptype() == 'NONE'`);
  `bubble.say("hi", chime=True)` does not raise. (extend
  `tests/test_smoke_bubble.py`)
- **pet.pyw (Windows-only smoke):** launching the cat with a started focus timer
  shows the badge (`cat.timerbadge` present, `show` reached) without raising;
  full-suite launch proves no import/wiring breakage. (extend
  `tests/test_smoke_pet.py`)

## Constraints (carry verbatim into the plan)

- Pure Python 3.12 stdlib only — **no pip, ever** (tkinter, ctypes, winsound,
  wave, json, time, os, re).
- Win32 stays in `winkit/`; pet feature logic + GUI pieces stay in `petkit/`
  (precedent: `petkit/bubble.py`).
- Pure logic takes injected clock/now values (no `time.*` inside pure functions).
- TDD: failing test first, watch it fail, minimal code to pass.
- `assets/meow.wav` MUST be a PCM WAV that the stdlib `wave` module opens with
  `comptype == 'NONE'` (else `winsound.PlaySound` is silent).
- Reminder `repeat` is the only new field; values limited to `"none"`/`"daily"`;
  old `reminders.json` entries load as one-time. **No new `config.json` keys.**
- Test runner (bare `python` is a broken MS-Store stub → exit 49):
  `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe`
- Commit after each task; end commit messages with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`
