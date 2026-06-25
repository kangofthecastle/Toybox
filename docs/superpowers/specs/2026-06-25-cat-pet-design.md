# Music-Reactive Cat Pet — Design

**Date:** 2026-06-25
**Status:** Proposed (design), pending user review → plan
**Runtime:** Python 3.12 stdlib only (tkinter + ctypes + winreg). Reuses/extends the `winkit` package; adds a `petkit` package.

## Overview

Replace the procedurally-drawn vector blob pet with a **pixel-art cat** (from the `CatPackFree` sprite pack) and grow it from a music toy into a lightweight desktop **companion + assistant**. The cat keeps everything the blob did — always-on-top, draggable, transparent/click-through margin, music reactivity, adaptive frame rate — but renders as animated sprites, reacts with a colored **glow aura**, gains **cursor-tracking pupils**, and hosts eleven opt-in abilities ranging from pure cat charm (petting, naps) to real utilities (focus timer, reminders, window pin, file courier).

Hard requirement throughout: **super lightweight**. No third-party packages. Every ability is event-driven or low-poll; per-frame work stays O(1); the cat *lowers* its own frame rate when idle/napping.

## Goals / Non-goals

**Goals:** A faithful pixel-art cat on the existing transparent overlay; music-reactive glow (cat keeps its true colors); cursor-tracking pupils that stay glued across animation frames; a reusable speech-bubble + right-click-menu interaction surface; eleven abilities (below); clean separation of OS glue (`winkit`) from pet features (`petkit`); pure-stdlib and lightweight.

**Non-goals (explicitly cut):** Mouse Hunter (pounce-chase), Herd (mass-minimize), CPU/RAM body-language (the dropped system watchdog), Purr soundscape (ambient sound player). Anything needing network/API keys, an LLM, voice, or screen OCR/vision. The `Furnitures.png` tileset is unused. The cursor-eye-tracking is kept but reimplemented for sprites (overlay pupils), not the vector pupils.

## The art (`CatPackFree/CatPackFree/`)

Pixel-art, 32×32 frames, **strictly binary alpha (0/255)** — verified, so the color-key overlay shows the cat with **no fringe** and nearest-neighbor scaling stays crisp.

| Sheet | Size | Frames | Use |
|---|---|---|---|
| `Idle.png` | 320×32 | 10 | default idle (tail swish) |
| `Box3.png` | 128×32 | 4 | Box Catnap (sleeping in a box) |
| `drculacat.png` | 192×32 | 6 | optional night/easter-egg "vampire" skin |
| `Furnitures.png` | 512×512 | — | unused |

Sprites are bundled into the repo (copied under `assets/cat/`) so the pet does not depend on the Downloads folder.

## Components & files

```
pet.pyw                # rewritten: sprite window, main tick + state machine, glow,
                       #   pupils, drag, right-click menu, wires petkit modules
assets/cat/*.png       # bundled sprite sheets (Idle, Box3, drculacat)

winkit/sprites.py      # NEW: PNG sheet -> cached tk PhotoImage frames (crop + zoom)
winkit/input.py        # EXTEND: idle_ms() via GetLastInputInfo
winkit/window.py       # EXTEND: pin_window_at_cursor()/topmost toggle helpers
winkit/dnd.py          # NEW: accept WM_DROPFILES on the pet HWND; build CF_HDROP

petkit/__init__.py     # NEW package: pet features, one focused file each
petkit/bubble.py       # speech bubble (transient transparent Toplevel) + winsound chime
petkit/persona.py      # time-of-day bucket -> glow palette + greeting tone
petkit/reactions.py    # petting detection, nap/box state, blink, startle (pure-ish)
petkit/pomodoro.py     # focus/Pomodoro timer state machine
petkit/reminders.py    # parse + persist + fire reminders
petkit/nudges.py       # activity-gated break/posture nudges
petkit/focus_tracker.py# per-app foreground-time tally + distraction nudge
petkit/clip_actions.py # clipboard quick-actions (math / URL / hex color)
petkit/greeter.py      # welcome-back after idle

config.py              # EXTEND the "pet" section (per-ability settings/toggles)
reminders.json         # generated at runtime; pending reminders
```

`winkit` stays the reusable native layer shared by all toys; `petkit` holds pet-only feature logic. Files that change together live together; each file has one responsibility.

## Rendering

**Sprite engine (`winkit/sprites.py`, testable).** `SpriteSheet(path, frame_w=32)` loads the PNG once as a `tk.PhotoImage`, exposes `frame_count`, and `frame(i, zoom)` → a cached `PhotoImage` cropped to frame `i` (`image.tk.call(dst,'copy',src,'-from',x0,0,x1,32,'-to',0,0)`) and integer-`zoom()`ed (nearest-neighbor). Frames are cached per `(i, zoom)`. Pure rendering; unit-testable for frame count/size.

**Window.** Same as today: `WIN`-sized borderless, `-topmost`, `-transparentcolor` color-key overlay; a `Canvas` with `bg = KEY_COLOR`. The cat is a single `canvas.create_image` item whose image is swapped per frame. Transparent sprite pixels = key color = click-through; opaque pixels are grabbable for drag. Cat target size ≈ 128 px (zoom 4).

**Animation state machine** (in `pet.pyw`). States: `idle`, `petted`, `napping` (Box3), `startled`, optional `vampire` (drculacat). Each state owns a sheet + frame cadence; the tick advances the frame index by elapsed time and swaps the image. Music beats add hops/wiggle exactly as today (`_start_hop`, `wiggle_amp`), now applied as a vertical offset of the image item rather than polygon math.

**Glow (color choice = glow only).** One (or two stacked) `create_oval` behind the cat, large soft ellipse. Per frame: `itemconfig(fill=...)` where intensity follows the music `envelope` (pulse) and base hue comes from `persona` (time of day). Pure `itemconfig` — no pixel work, negligible cost. The cat keeps its cream colors.

**Pupils (cursor tracking on sprites).** A per-state table of **eye anchor points per frame** — `EYES[state][frame] = ((lx,ly),(rx,ry))` in 32-space, scaled by zoom — because the cat's eyes drift a few px across the idle frames. Two small `create_oval` pupils are re-seated to the current frame's anchors each tick and deflected toward the global cursor (reusing today's clamp math). Pupils are colored to match the art's eyes (near-black). Blink reuses the lid-line trick / or hides pupils briefly. Anchor tables are produced once by sampling the sprites (offline helper) and stored as constants.

**Notifications substrate (`petkit/bubble.py`).** The pet owns no tray icon, so it "talks" via a **speech bubble**: a small transient `Toplevel` (overrideredirect, topmost, transparentcolor, rounded rect + text) placed just above the cat, shown ~3 s then destroyed. `bubble.say(root, text, secs=3)`. Optional `winsound.PlaySound(..., SND_ASYNC)` chime for timers/reminders. Every ability that needs to surface info uses the bubble — no second tray icon.

**Right-click menu.** `<ButtonPress-3>` on the canvas opens a `tk.Menu`: Focus (25 m / custom…), Add reminder…, ability toggles, skin (Idle / Box / Vampire), and Settings. Left-click stays drag-only.

## Lightweight discipline

- Adaptive frame rate unchanged: ~8 fps idle, ~30 fps when audio present or cursor moving.
- A single **IdleService** reads `GetLastInputInfo` once per tick (microseconds) and feeds Box Catnap, nudges, and the greeter — no extra loops.
- App-focus is sampled every ~3 s, not per frame.
- Clipboard quick-actions ride the existing clipboard **sequence-number** change check — zero cost when nothing is copied.
- Box Catnap throttles the tick to ~2 fps while sleeping (a net CPU *win*).
- Per-frame cost is O(1): one image swap, one glow `itemconfig`, two pupil moves.

## Abilities

Each ability is a `petkit` module the pet constructs and wires; each can be toggled in config. Pure logic is TDD'd; Win32 bits get Windows-only integration smoke tests.

### Core companion

1. **Time-of-day persona** (`persona.py`). `datetime.now()` → bucket (morning/day/evening/night) → glow base hue + greeting tone; cat gets "sleepy" after long silence. Optional: night bucket may offer the vampire skin. *Pure* bucketing logic is unit-tested.

2. **App-focus tracker** (`focus_tracker.py`). Every ~3 s: `GetForegroundWindow` → `GetWindowThreadProcessId` → `QueryFullProcessImageNameW` for a stable app name (fallback `GetWindowTextW`). Accumulate seconds per app in memory (+ optional daily JSON). Right-click / hover shows today's top apps; an optional gentle bubble after a long unbroken stretch on one app ("40 min on X"). Fully local. Accumulation logic is unit-tested with synthetic samples.

3. **Petting & Purr** (`reactions.py`). `<Motion>` over the canvas feeds a detector that counts cursor direction-reversals within the sprite over a short window; enough → "petting": cat squints (pupils→arcs), leans toward the cursor, shows a `purr~` bubble, accumulates affection. Long neglect biases toward napping. Event-driven; reversal-counting logic is unit-tested with synthetic cursor tracks.

4. **Box Catnap** (`reactions.py`). When `idle_ms()` exceeds a threshold, transition to the **Box3** skin, sleep (occasional `Zzz` bubble), throttle fps to ~2; on input return → `startled` hop, back to `idle`, then hand off to the greeter. Transition logic unit-tested with injected idle values.

### Assistant

5. **Reminders** (`reminders.py`). Parse `"remind me in 20m"`, `"in 1h30"`, `"at 3pm"` via regex + `datetime`; persist pending reminders to `reminders.json` (atomic write); a low-rate timer fires due ones via bubble + chime. Add/list/cancel from the right-click menu (+ a tiny entry dialog). Parsing + due-detection are unit-tested; no network.

6. **Focus / Pomodoro timer** (`pomodoro.py`). Right-click → Focus 25 m (configurable). A single `after()` chain runs the countdown; the cat reflects it (subtle glow ring / posture); on done → chime + bubble, then a 5 m break state. Pause/resume/cancel from the menu. State machine is unit-tested with an injected clock.

7. **Break / posture nudges** (`nudges.py`). After N minutes of **real activity** (gated by `idle_ms()` so it never nags while you're away), the cat stretches and bubbles a "stretch?" nudge; snooze/dismiss. Default ~50 min, configurable. Gating + scheduling logic unit-tested.

8. **Welcome-back greeting** (`greeter.py`). Using `idle_ms()`: when idle crosses a threshold (e.g. 5 min) and then activity resumes, the cat greets you (bubble), optionally noting time away. Coordinates with Box Catnap (nap during idle → startle + greet on return). Logic unit-tested.

9. **Clipboard quick-actions** (`clip_actions.py`). On a clipboard **sequence-number** change, inspect the text: a safe arithmetic expression → evaluate via a whitelisted-`ast` evaluator → bubble the result ("= 22, copy?"); a URL → bubble "open?" (`os.startfile`); a hex color → bubble a swatch. Read-only (coexists with the separate Clipboard toy). The safe evaluator, URL test, and hex test are unit-tested (incl. rejecting unsafe input).

### Power-tools

10. **Pin** (`winkit/window.py` + wiring). A configurable hotkey (via the existing `HotkeyPoller`): `WindowFromPoint(GetCursorPos())` → `GetAncestor(GA_ROOT)` → toggle `SetWindowPos` `HWND_TOPMOST`/`HWND_NOTOPMOST`; track pinned hwnds in a set; feedback via a paw-badge bubble / brief glow. Keeps a video/reference/notes window floating over everything. Event-driven; topmost-toggle covered by a Windows smoke test.

11. **Catch & Carry** (`winkit/dnd.py` + wiring). `shell32.DragAcceptFiles(hwnd, True)`; subclass the pet HWND's wndproc (`SetWindowLongPtrW(GWLP_WNDPROC, …)`, chaining the original via `CallWindowProcW`) to handle **WM_DROPFILES** → `DragQueryFileW` for dropped path(s); the cat "holds" them (mini file glyph/bubble). To release: rebuild the clipboard as **CF_HDROP** (a `DROPFILES` struct + double-null path list) via `OpenClipboard`/`EmptyClipboard`/`SetClipboardData`, so a normal **Ctrl+V** in Explorer drops the file there; or click the cat to clear. The `DROPFILES`/`CF_HDROP` byte layout is unit-tested; drop receipt is a Windows smoke test. (Most complex native piece — isolated in its own module.)

## Data / persistence

- `config.json` gains a richer `"pet"` section: per-ability enable flags and settings (focus length, nudge interval, idle thresholds, pin hotkey, glow palette, skin). `config.py` `_coerce` extended with defaults.
- `reminders.json`: list of `{text, due_epoch}`; atomic write; missing/corrupt → empty (no crash).
- App-focus daily tally: in-memory; optional small JSON keyed by date (best-effort).

## Testing strategy

**Pure logic (TDD, cross-platform):** sprite frame indexing math; persona time bucketing; petting reversal detection; Box Catnap / greeter idle state machines (injected idle values); reminder parsing + due detection; Pomodoro state machine (injected clock); nudge gating; clipboard safe-`ast` math evaluator + URL/hex detectors; `DROPFILES`/CF_HDROP byte builder; focus-tally accumulation.

**Win32 integration smoke (Windows-only, like `test_winkit_system.py`):** `idle_ms()` returns a plausible int; `SpriteSheet` loads and yields the right frame count/size under a hidden Tk root; pin topmost toggle flips the ex-style; `DragAcceptFiles` succeeds on a real HWND.

**GUI smoke (`TOYBOX_SMOKE` auto-close) + screenshot:** the cat renders on the overlay (no fringe), glow + pupils draw, a bubble appears, the menu builds. Reuses the existing smoke harness.

## Phasing (each a working, shippable slice)

1. **"It's a cat"** — `winkit/sprites.py`, sprite window + animation state machine, music-reactive glow, cursor-tracking pupils, drag/persist, time-of-day persona. Replaces the blob with a fully reactive cat.
2. **"Alive"** — `petkit/bubble.py` + right-click menu substrate, Petting & Purr, Box Catnap (+ `idle_ms()`), welcome-back greeter.
3. **"Assistant"** — Pomodoro timer, reminders, break nudges, app-focus tracker, clipboard quick-actions.
4. **"Power-tools"** — Pin (`winkit/window.py`), Catch & Carry (`winkit/dnd.py`).

Each phase ends with green tests and a runnable pet; later phases only add modules + menu wiring, not rewrites.

## Risks & mitigations

- **Pupil drift across frames** → per-frame anchor table sampled offline; verified by screenshot smoke.
- **WM_DROPFILES on a Tk window** (Tk owns the wndproc) → subclass via `SetWindowLongPtrW` + `CallWindowProcW`, isolated in `winkit/dnd.py`; 64-bit-safe types as in `winkit/tray.py`.
- **Scope (11 abilities)** → strict phasing; abilities are independent toggleable modules, so any can slip a phase without blocking the cat itself.
