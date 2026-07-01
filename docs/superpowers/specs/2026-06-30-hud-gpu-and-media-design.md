# HUD: GPU usage row + media controls — Design

**Date:** 2026-06-30
**Status:** Approved (design)
**Branch:** `hud-gpu-and-media` (one branch, both features, off `main`)
**Runtime:** Python 3.12 stdlib only (tkinter + ctypes). Extends the System
Monitor HUD (`hud.pyw`), the pure `sysmetrics.py`, and `winkit/`. No pip, ever.

## Problem

The HUD shows live **CPU%** and **RAM%** (via `winkit/metrics.py` →
`GetSystemTimes` / `GlobalMemoryStatusEx`), a clock, and sparklines. Two gaps:

1. **GPU usage was never built.** It was listed only as an explicit *non-goal*
   in the web-feed plugin spec ("local sensor tiles (GPU usage, disk free
   space)… deferred to a separate spec") and the plan confirmed none were
   implemented. This is that separate spec.
2. **No media controls.** There is no way to play/pause or skip tracks from the
   HUD.

## Goals

- A third metric row — `GPU  NN%` + scrolling sparkline — rendered identically
  to the CPU/RAM rows, sampling real GPU utilization.
- A row of three media-control glyphs (`⏮ ⏯ ⏭`) that send system media keys,
  working with any player (Spotify, browser, etc.).
- Both rows **always visible** (no toggles/config). GPU degrades gracefully to
  a dim `GPU --%` when the machine exposes no GPU perf counters.

## Non-goals (deferred, matching the original spec)

- Now-playing metadata (track title / artist / album art) — needs WinRT SMTC,
  which has no clean pure-stdlib path. Media is **controls-only**: play/pause is
  a single honest toggle, since play state is not read.
- GPU temperature, disk-free, fan-speed sensors; per-player targeting; CPU-temp.

## Approach

Follows the established split: **pure math in `sysmetrics.py`** (unit-tested, no
ctypes), **Win32 ctypes in `winkit/`**, and `hud.pyw` wiring it together.

### GPU usage

Measured via **PDH (Performance Data Helper)** through `ctypes` on `pdh.dll` (a
system DLL — no pip). Counter: `\GPU Engine(*)\Utilization Percentage`, a
wildcard over all GPU-engine instances.

Verified present on the target machine via `typeperf -qx`; instance names look
like:

```
\GPU Engine(pid_11700_luid_..._eng_0_engtype_3D)\Utilization Percentage
\GPU Engine(pid_11700_luid_..._eng_13_engtype_Copy)\Utilization Percentage
\GPU Engine(pid_11700_luid_..._eng_10_engtype_Cuda)\Utilization Percentage
```

**Pure aggregation — `sysmetrics.gpu_percent(instances)`** (new, testable, no
ctypes): takes an iterable of `(instance_name, value)` pairs (or a mapping).

1. Parse the `engtype_<Type>` token from each instance name (e.g. `3D`, `Copy`,
   `Cuda`, `VideoDecode`). Instances without an `engtype_` token are ignored.
2. **Sum** the values of all instances sharing an engine type (there are often
   several `Copy` engines).
3. Return the **max** across engine-type sums, clamped to `[0, 100]`.
4. Empty / no parseable instances → return `None` (the "no GPU data" signal).

This approximates Task Manager's GPU% (busiest engine wins). It's a float.

**Stateful sampler — `winkit/metrics.GpuSampler`** (new, ctypes), mirroring
`CpuSampler`:

- `__init__`: `PdhOpenQuery` → `PdhAddEnglishCounter` (locale-independent) for
  the wildcard path → one `PdhCollectQueryData` as the baseline. If any PDH call
  fails (or `pdh.dll` is unavailable), set an `_ok = False` flag and never raise.
- `sample() -> float | None`: if `not _ok`, return `None`. Otherwise
  `PdhCollectQueryData` then `PdhGetFormattedCounterArray(PDH_FMT_DOUBLE)` to read
  every instance, build `(name, value)` pairs, and return
  `sysmetrics.gpu_percent(pairs)`. The **first** `sample()` after init may read
  `0.0` (utilization counters are time-based and need two collections) — same
  baseline contract as `CpuSampler.sample()`. On any per-sample PDH error,
  return `None` (transient failure must not crash the tick).

`PdhGetFormattedCounterArray` is called twice per tick per PDH convention: once
with a NULL buffer to learn the required size, then with an allocated buffer.
Buffer entries are `PDH_FMT_COUNTERVALUE_ITEM` (a `szName` pointer + a
`PDH_FMT_COUNTERVALUE` union); we read the `.doubleValue`.

### Media controls

**New module — `winkit/media.py`** (ctypes on `user32.dll`): synthesizes media
virtual-key presses via `keybd_event(vk, 0, 0, 0)` (down) + `keybd_event(vk, 0,
KEYEVENTF_KEYUP, 0)` (up).

```
play_pause()   -> VK_MEDIA_PLAY_PAUSE  (0xB3)
next_track()   -> VK_MEDIA_NEXT_TRACK  (0xB0)
prev_track()   -> VK_MEDIA_PREV_TRACK  (0xB1)
```

Player-agnostic; no now-playing state is read. Failures are swallowed (a media
key that no app consumes is a no-op, not an error).

### HUD layout & wiring — `hud.pyw`

The fixed header grows from **3 rows to 5**: CPU / RAM / GPU / clock / media.
Feeds still flow below via the existing dynamic `_resize()`.

```
┌─ HUD ──────────────┐
│ CPU  12%  ▁▂▅▃      │
│ RAM  48%  ▃▃▄▄      │
│ GPU   7%  ▁▁▂▁      │   ← new (green sparkline, e.g. #7ee787)
│      14:22:07      │
│   ⏮   ⏯   ⏭        │   ← new
│  ── feeds below ── │
└────────────────────┘
```

Changes:

- **State:** add `GpuSampler`, `gpu_hist` deque, `gpu` value (mirrors cpu/ram).
- **Layout constants:** add a GPU sparkline band `(PAD + 2*ROW_H + 1, PAD +
  3*ROW_H - 1)`; shift the clock to row 4 and add a media row 5; bump base
  `HEIGHT` (~96 → ~128) and the feed baseline from `PAD + 3*ROW_H + 4` to
  `PAD + 5*ROW_H + 4`.
- **GPU row render:** a persistent `GPU  NN%` text + a persistent sparkline line
  reusing `_update_spark`. When `sample()` returns a float, render `GPU  NN%` and
  append it to `gpu_hist`. When it returns `None`, render a dim `GPU --%` and do
  **not** append — leaving `gpu_hist` short keeps `_update_spark` in its existing
  `n < 2` hidden state (a machine with no GPU counters never grows the deque).
- **Media row:** three persistent text items `⏮ ⏯ ⏭`, centered and evenly
  spaced, rendered in **Segoe UI Symbol** (Consolas lacks these glyphs; Segoe UI
  Symbol ships on all Win10). A dedicated `_media_hits` list of
  `(x0, x1, y0, y1, fn)` zones.
- **Click handling:** in `_on_release`, on a **non-drag** click, check
  `_media_hits` first (before feed actions / URL opens) and call the matching
  `winkit.media` function. Dragging the HUD by the media row still works because
  the fire only happens when `not self._moved` (existing pattern).
- `tick()` also does `self.gpu = self.gpu_sampler.sample()` and appends to
  `gpu_hist` **only when the sample is a float** (skips the append on `None`).

The GPU sample runs on the UI thread like `CpuSampler`; `PdhCollectQueryData` is
sub-millisecond, so the 1 Hz tick is unaffected.

## Testing strategy (TDD)

**Unit — `tests/test_sysmetrics.py` (extend) / new `test_gpu_percent`, pure:**
- Single engtype: `[("..._engtype_3D", 40.0)]` → `40.0`.
- Sum within a type: two `engtype_Copy` instances `30 + 25` → `55.0` when that's
  the max.
- Max across types wins: `3D=40`, `Copy=55` → `55.0`.
- Clamp: a summed type over 100 → `100.0`.
- No parseable instances / empty → `None`.
- Instances lacking an `engtype_` token are ignored.

**Unit — new `tests/test_media.py`, ctypes stubbed:**
- Monkeypatch the module's `keybd_event` to record `(vk, flags)` calls; assert
  `play_pause` / `next_track` / `prev_track` each emit the correct VK as a
  down (flags 0) then up (`KEYEVENTF_KEYUP`) pair.

**Smoke — `tests/test_smoke_hud.py` (extend, Windows-only):** the HUD still
launches with the taller 5-row header and exits cleanly with empty stderr; assert
the GPU row and the three media glyphs are present as canvas text. `GpuSampler`
runs against real PDH under smoke (no network); a machine without GPU counters
falls to the `--%` path, which the test tolerates.

## Constraints (carry verbatim into the plan)

- Pure Python 3.12 stdlib only — **no pip, ever** (tkinter, ctypes).
- Win32 stays in `winkit/`: GPU PDH ctypes in `winkit/metrics.py` (with
  `CpuSampler`); media ctypes in new `winkit/media.py`. Pure GPU aggregation
  lives in `sysmetrics.py` (no ctypes, no Tk).
- GPU never crashes the tick: every PDH failure path returns `None`/degrades to
  `GPU --%`.
- Media failures are swallowed (no-op if unconsumed).
- Media glyphs render in **Segoe UI Symbol**; verify they are not tofu when the
  HUD is run.
- Both rows always on — no config keys, no menu items.
- TDD: failing test first, watch it fail, minimal code to pass. Commit per task.
- Test runner (bare `python` is a broken MS-Store stub → exit 49):
  `C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe`
- End commit messages with:
  `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`
