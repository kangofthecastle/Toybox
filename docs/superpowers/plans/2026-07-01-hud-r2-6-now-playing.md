# Now-Playing Progress Bar + Track Title Implementation Plan

> For agentic workers: use subagent-driven-development to execute; steps use checkbox syntax.

**Goal:** Add a now-playing reader that snapshots the current Windows System
Media Transport Controls (SMTC) session and renders, under the HUD's existing
media buttons, a `title — artist` line plus a thin progress bar. The layout
reserves fixed vertical space so the header never jumps when playback
starts/stops. This is Feature 2 of the HUD Enhancements Round 2 design.

**Architecture:** A new pure-stdlib module `winkit/nowplaying.py` mirrors the
`winkit/media.py` shape: a small set of pure, fully unit-tested helpers plus one
blanket-guarded ctypes reader `read()` that can never raise. `read()` walks the
WinRT `GlobalSystemMediaTransportControlsSessionManager` flow via `combase.dll`.
`hud.pyw` gains a daemon poll thread (~2.5 s) that stores the latest sample under
a lock, three persistent canvas items (title text + progress-bar track + fill),
and a `_draw_nowplaying()` tick step that advances the displayed position with
wall-clock time so the bar animates smoothly between reads. The now-playing band
is inserted between the media row and the clock/expand row; `HEIGHT`, the
clock/expand row offset, and the feed-column top all shift down by a single
reserved-height constant. The persistent `title — artist` line renders static
and centered when it fits; when it overflows the tile width it auto-scrolls
(music-player ticker: scroll left to reveal the end, then jump back to the
start — never bouncing) via a small pixel-motion loop (`_np_marquee_step`) that
reuses the feed marquee's wrap math through a shared pure `marquee_step` stepper,
relying on the same canvas-edge clipping the feed marquee already uses to hide
overflow.

**Tech Stack:** Python 3.12 standard library only. `ctypes` (WinRT via
`combase.dll` / `ole32.dll`), `threading` (poll daemon), `tkinter` (canvas
render). No third-party packages.

## Global Constraints

- Pure Python 3.12 stdlib; no third-party packages.
- Never weaken urllib default TLS; only http/https may reach the browser.
- config.json is gitignored and holds a live GitHub PAT — never echo/log/commit it; every runtime config write goes through config.update(path, {...}) (scoped read-modify-write) so it cannot clobber another toy's keys.
- The HUD must never crash on bad external input: every parser returns a safe default; every ctypes/WinRT/Tk call is guarded (try/except).
- Lightweight: no busy loops; background polling is mtime/interval-gated.
- Test runner — use this EXACT command form in every "run the test" step:
    C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest <dotted.path> -v
  run from the repo root. Bare "python" is broken on this machine.
- Commit trailer, EXACTLY (every commit step ends with this line):
    Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

Note on now-playing needing no config: it renders whenever a session exists and
writes nothing to config.json, so the config-clobber / restart-all-toys concern
does not apply to this feature.

---

## Task 1: Pure now-playing helpers + NowPlaying record

Create `winkit/nowplaying.py` with the `NowPlaying` namedtuple and the three
pure helpers (`progress_fraction`, `advance`, `format_track`). No WinRT yet.

**Files:**
- Create: `winkit/nowplaying.py`
- Test: `tests/test_nowplaying.py`

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces:
  - `NowPlaying(title, artist, status, position_s, duration_s, sampled_at)` — a `collections.namedtuple`.
  - `progress_fraction(position_s, duration_s) -> float` in `[0, 1]`.
  - `advance(position_s, elapsed_s, status) -> float` (adds wall-clock only while `status == "playing"`).
  - `format_track(title, artist) -> str`.

### Steps

- [ ] Step: write the failing test — create `tests/test_nowplaying.py`:

```python
import unittest

import winkit.nowplaying as nowplaying


class TestProgressFraction(unittest.TestCase):
    def test_zero_duration_is_zero(self):
        self.assertEqual(nowplaying.progress_fraction(10.0, 0.0), 0.0)

    def test_negative_duration_is_zero(self):
        self.assertEqual(nowplaying.progress_fraction(10.0, -5.0), 0.0)

    def test_quarter(self):
        self.assertAlmostEqual(nowplaying.progress_fraction(30.0, 120.0), 0.25)

    def test_clamps_over_one(self):
        self.assertEqual(nowplaying.progress_fraction(200.0, 120.0), 1.0)

    def test_negative_position_is_zero(self):
        self.assertEqual(nowplaying.progress_fraction(-3.0, 120.0), 0.0)

    def test_bad_input_is_zero(self):
        self.assertEqual(nowplaying.progress_fraction(None, None), 0.0)


class TestAdvance(unittest.TestCase):
    def test_playing_adds_elapsed(self):
        self.assertAlmostEqual(nowplaying.advance(30.0, 5.0, "playing"), 35.0)

    def test_paused_holds(self):
        self.assertAlmostEqual(nowplaying.advance(30.0, 5.0, "paused"), 30.0)

    def test_stopped_holds(self):
        self.assertAlmostEqual(nowplaying.advance(30.0, 5.0, "stopped"), 30.0)

    def test_negative_elapsed_ignored(self):
        self.assertAlmostEqual(nowplaying.advance(30.0, -5.0, "playing"), 30.0)

    def test_never_negative(self):
        self.assertEqual(nowplaying.advance(-10.0, 0.0, "paused"), 0.0)

    def test_bad_input(self):
        self.assertEqual(nowplaying.advance(None, None, "playing"), 0.0)


class TestFormatTrack(unittest.TestCase):
    def test_title_and_artist(self):
        self.assertEqual(nowplaying.format_track("Song", "Band"), "Song — Band")

    def test_title_only(self):
        self.assertEqual(nowplaying.format_track("Song", ""), "Song")

    def test_artist_only(self):
        self.assertEqual(nowplaying.format_track("", "Band"), "Band")

    def test_both_empty(self):
        self.assertEqual(nowplaying.format_track("", ""), "")

    def test_none_inputs(self):
        self.assertEqual(nowplaying.format_track(None, None), "")

    def test_trims_whitespace(self):
        self.assertEqual(nowplaying.format_track("  Song ", " Band "), "Song — Band")


class TestNowPlayingRecord(unittest.TestCase):
    def test_fields_in_order(self):
        s = nowplaying.NowPlaying("t", "a", "playing", 1.0, 2.0, 3.0)
        self.assertEqual(s.title, "t")
        self.assertEqual(s.artist, "a")
        self.assertEqual(s.status, "playing")
        self.assertEqual(s.position_s, 1.0)
        self.assertEqual(s.duration_s, 2.0)
        self.assertEqual(s.sampled_at, 3.0)


if __name__ == "__main__":
    unittest.main()
```

- [ ] Step: run it, expect FAIL — the module does not exist yet.

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_nowplaying -v
```

Expected failure: `ModuleNotFoundError: No module named 'winkit.nowplaying'`
(collection error, 0 tests run).

- [ ] Step: implement — create `winkit/nowplaying.py` with exactly:

```python
"""Now-playing reader for the current Windows System Media Transport Controls
(SMTC) session, via WinRT through ctypes. read() returns a NowPlaying snapshot
or None and NEVER raises, on any machine (no session, WinRT missing, COM error).
Also holds pure, unit-tested helpers the HUD uses to animate the progress bar
smoothly between reads. Pure Python 3.12 stdlib -- no pip."""
from collections import namedtuple

NowPlaying = namedtuple(
    "NowPlaying", "title artist status position_s duration_s sampled_at")


def progress_fraction(position_s, duration_s):
    """Fraction played in [0, 1]. 0.0 when duration is non-positive/invalid or
    the position is non-positive; 1.0 when the position meets/exceeds duration."""
    try:
        d = float(duration_s)
        p = float(position_s)
    except (TypeError, ValueError):
        return 0.0
    if d <= 0 or p <= 0:
        return 0.0
    if p >= d:
        return 1.0
    return p / d


def advance(position_s, elapsed_s, status):
    """Displayed position after `elapsed_s` wall-clock seconds. Adds elapsed only
    while playing; holds otherwise. Never returns a negative number."""
    try:
        p = float(position_s)
    except (TypeError, ValueError):
        p = 0.0
    if status == "playing":
        try:
            e = float(elapsed_s)
        except (TypeError, ValueError):
            e = 0.0
        if e > 0:
            p += e
    return p if p > 0 else 0.0


def format_track(title, artist):
    """'title — artist'; title alone when artist empty; artist alone when
    title empty; '' when both empty. Whitespace-trimmed."""
    t = (title or "").strip()
    a = (artist or "").strip()
    if t and a:
        return "%s — %s" % (t, a)
    return t or a
```

- [ ] Step: run it, expect PASS.

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_nowplaying -v
```

- [ ] Step: commit.

```
git add winkit/nowplaying.py tests/test_nowplaying.py
git commit -m "Add pure now-playing helpers (progress_fraction, advance, format_track)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Guarded WinRT SMTC reader `read()`

Append the ctypes WinRT reader to `winkit/nowplaying.py`. Everything runs inside
one blanket try/except: any failure (no session, WinRT unavailable, COM error,
non-Windows) returns `None`. Only a smoke test — it must return `None` or a
well-formed `NowPlaying` and never raise, on any machine.

**Files:**
- Modify: `winkit/nowplaying.py`
- Test: `tests/test_nowplaying.py`

**Interfaces:**
- Consumes: `combase.dll` (WinRT: `RoInitialize`, `RoGetActivationFactory`, `WindowsCreateString`, `WindowsDeleteString`, `WindowsGetStringRawBuffer`) and `ole32.dll` (`CLSIDFromString`), all via ctypes.
- Produces: `read() -> NowPlaying | None` (guarded, never raises).

**ctypes flow (all guarded, HRESULT-checked; any non-zero HRESULT or null
pointer short-circuits to `None`):**
`RoInitialize(RO_INIT_MULTITHREADED)` (ignoring the already-initialized HRESULT)
-> `WindowsCreateString(class name)` -> `RoGetActivationFactory(hstr, statics
IID, &factory)` -> factory `RequestAsync` (vtable slot 6) -> poll the returned
`IAsyncOperation` via `IAsyncInfo.get_Status` (QI to the well-known IAsyncInfo
IID; Status slot 7) until `Completed` (bounded ~1 s) -> `GetResults` (slot 8) =
the session manager -> `GetCurrentSession` (slot 6; null -> nothing playing ->
`None`) -> `GetTimelineProperties` (slot 7) reads `StartTime`/`EndTime`/`Position`
as Int64 100-ns TimeSpans (slots 6/7/10) -> `GetPlaybackInfo` (slot 8) ->
`get_PlaybackStatus` (slot 7; 4=Playing, 5=Paused, else stopped) ->
`TryGetMediaPropertiesAsync` (slot 6), polled the same way, then `get_Title`
(slot 6) / `get_Artist` (slot 8) HSTRINGs decoded via
`WindowsGetStringRawBuffer`. Every acquired COM pointer is `Release`d and every
HSTRING `WindowsDeleteString`d in `finally` blocks. WinRT interface method slots
begin at 6 (IUnknown 0-2, IInspectable 3-5).

### Steps

- [ ] Step: write the failing test — append this class to `tests/test_nowplaying.py`
(before the `if __name__ == "__main__":` block):

```python
class TestReadSmoke(unittest.TestCase):
    def test_read_never_raises_and_is_well_shaped(self):
        # On any machine: returns None or a valid NowPlaying, and never raises.
        s = nowplaying.read()
        if s is not None:
            self.assertIsInstance(s, nowplaying.NowPlaying)
            self.assertIn(s.status, ("playing", "paused", "stopped"))
            self.assertIsInstance(s.title, str)
            self.assertIsInstance(s.artist, str)
            self.assertGreaterEqual(s.position_s, 0.0)
            self.assertGreaterEqual(s.duration_s, 0.0)
            self.assertIsInstance(s.sampled_at, float)

    def test_read_is_idempotent_no_raise(self):
        # Calling twice (re-entrant RoInitialize path) must also never raise.
        nowplaying.read()
        nowplaying.read()
```

- [ ] Step: run it, expect FAIL — `read` does not exist yet.

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_nowplaying.TestReadSmoke -v
```

Expected failure: `AttributeError: module 'winkit.nowplaying' has no attribute 'read'`.

- [ ] Step: implement — append to `winkit/nowplaying.py` (after `format_track`):

```python
# --- WinRT SMTC reader (guarded; never raises) ---------------------------
import ctypes
import time

_RO_INIT_MULTITHREADED = 1
_ASYNC_STARTED = 0
_ASYNC_COMPLETED = 1
_STATUS_PLAYING = 4
_STATUS_PAUSED = 5
_TICKS_PER_S = 10_000_000.0   # WinRT TimeSpan/DateTime unit is 100 ns

_MANAGER_CLASS = ("Windows.Media.Control."
                  "GlobalSystemMediaTransportControlsSessionManager")
# WinRT interface identifiers (brace form parsed by CLSIDFromString).
_IID_MANAGER_STATICS = "{2050C4EE-11A0-57DE-AED7-C97C70338245}"
_IID_ASYNC_INFO = "{00000036-0000-0000-C000-000000000046}"


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


def _guid(text):
    g = _GUID()
    ole32 = ctypes.WinDLL("ole32")
    if ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g)) != 0:
        raise OSError("bad IID")
    return g


def _vcall(ptr, slot, *args):
    """Call COM vtable method `slot` on interface pointer `ptr` (a c_void_p).
    All SMTC methods here return an HRESULT (c_long). Returns that HRESULT."""
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    fn_addr = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[slot]
    argtypes = [ctypes.c_void_p] + [ctypes.c_void_p] * len(args)
    proto = ctypes.WINFUNCTYPE(ctypes.c_long, *argtypes)
    return proto(fn_addr)(ptr, *args)


def _release(ptr):
    try:
        if ptr and ptr.value:
            _vcall(ptr, 2)   # IUnknown::Release
    except Exception:
        pass


def _await(op, deadline):
    """Poll an IAsyncOperation to completion (bounded by `deadline`, a monotonic
    time) then GetResults. Returns the result interface pointer or None."""
    info = ctypes.c_void_p()
    iid = _guid(_IID_ASYNC_INFO)
    if _vcall(op, 0, ctypes.byref(iid), ctypes.byref(info)) != 0 or not info.value:
        return None
    try:
        status = ctypes.c_int(_ASYNC_STARTED)
        while time.monotonic() < deadline:
            if _vcall(info, 7, ctypes.byref(status)) != 0:   # IAsyncInfo::get_Status
                return None
            if status.value != _ASYNC_STARTED:
                break
            time.sleep(0.01)
        if status.value != _ASYNC_COMPLETED:
            return None
        result = ctypes.c_void_p()
        if _vcall(op, 8, ctypes.byref(result)) != 0:         # IAsyncOperation::GetResults
            return None
        return result if result.value else None
    finally:
        _release(info)


def _hstring_to_str(combase, h):
    if not h:
        return ""
    length = ctypes.c_uint32(0)
    buf = combase.WindowsGetStringRawBuffer(h, ctypes.byref(length))
    if not buf or length.value == 0:
        return ""
    return ctypes.wstring_at(buf, length.value)


def _timespan_s(ptr, slot):
    """Read a WinRT TimeSpan (Int64 100-ns ticks) getter into seconds."""
    ticks = ctypes.c_int64(0)
    if _vcall(ptr, slot, ctypes.byref(ticks)) != 0:
        return 0.0
    return ticks.value / _TICKS_PER_S


def read():
    """Snapshot the current SMTC session, or None. NEVER raises."""
    try:
        return _read_impl()
    except Exception:
        return None


def _read_impl():
    combase = ctypes.WinDLL("combase.dll")
    combase.WindowsCreateString.argtypes = [
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    combase.WindowsDeleteString.argtypes = [ctypes.c_void_p]
    combase.WindowsGetStringRawBuffer.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    combase.WindowsGetStringRawBuffer.restype = ctypes.c_void_p
    combase.RoInitialize.argtypes = [ctypes.c_int]
    combase.RoGetActivationFactory.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]

    combase.RoInitialize(_RO_INIT_MULTITHREADED)   # RPC_E_CHANGED_MODE is fine

    cls = ctypes.c_void_p()
    if combase.WindowsCreateString(_MANAGER_CLASS, len(_MANAGER_CLASS),
                                   ctypes.byref(cls)) != 0 or not cls.value:
        return None
    factory = ctypes.c_void_p()
    manager = ctypes.c_void_p()
    session = ctypes.c_void_p()
    timeline = ctypes.c_void_p()
    playback = ctypes.c_void_p()
    props = ctypes.c_void_p()
    title_h = ctypes.c_void_p()
    artist_h = ctypes.c_void_p()
    try:
        iid = _guid(_IID_MANAGER_STATICS)
        if combase.RoGetActivationFactory(
                cls, ctypes.byref(iid), ctypes.byref(factory)) != 0 or not factory.value:
            return None
        op = ctypes.c_void_p()
        if _vcall(factory, 6, ctypes.byref(op)) != 0 or not op.value:
            return None
        try:
            manager = _await(op, time.monotonic() + 1.0)
        finally:
            _release(op)
        if not manager or not manager.value:
            return None
        if _vcall(manager, 6, ctypes.byref(session)) != 0 or not session.value:
            return None            # no active session -> nothing playing

        if _vcall(session, 7, ctypes.byref(timeline)) == 0 and timeline.value:
            start_s = _timespan_s(timeline, 6)
            end_s = _timespan_s(timeline, 7)
            position_s = _timespan_s(timeline, 10)
        else:
            start_s = end_s = position_s = 0.0
        duration_s = end_s - start_s if end_s > start_s else 0.0
        position_s = max(0.0, position_s - start_s)

        status = "stopped"
        if _vcall(session, 8, ctypes.byref(playback)) == 0 and playback.value:
            pstatus = ctypes.c_int(0)
            if _vcall(playback, 7, ctypes.byref(pstatus)) == 0:
                if pstatus.value == _STATUS_PLAYING:
                    status = "playing"
                elif pstatus.value == _STATUS_PAUSED:
                    status = "paused"

        title = artist = ""
        mop = ctypes.c_void_p()
        if _vcall(session, 6, ctypes.byref(mop)) == 0 and mop.value:
            try:
                props = _await(mop, time.monotonic() + 1.0)
            finally:
                _release(mop)
            if props and props.value:
                if _vcall(props, 6, ctypes.byref(title_h)) == 0:
                    title = _hstring_to_str(combase, title_h)
                if _vcall(props, 8, ctypes.byref(artist_h)) == 0:
                    artist = _hstring_to_str(combase, artist_h)

        return NowPlaying(title, artist, status, position_s, duration_s,
                          time.monotonic())
    finally:
        combase.WindowsDeleteString(cls)
        for h in (title_h, artist_h):
            try:
                combase.WindowsDeleteString(h)
            except Exception:
                pass
        for p in (props, playback, timeline, session, manager, factory):
            _release(p)
```

- [ ] Step: run it, expect PASS.

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_nowplaying -v
```

- [ ] Step: commit.

```
git add winkit/nowplaying.py tests/test_nowplaying.py
git commit -m "Add guarded WinRT SMTC reader nowplaying.read()

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: HUD integration — poll thread, render, reserved layout

Wire the reader into `hud.pyw`: a daemon poll thread stores the latest sample;
three persistent canvas items (title text, progress-bar track, progress-bar
fill) sit in a fixed reserved band inserted between the media row and the
clock/expand row; a `_draw_nowplaying()` tick step advances the position with
wall-clock time. The clock/expand row, the feed-column top, and `HEIGHT` all
shift down by the reserved-height constant so the header never jumps.

**Files:**
- Modify: `hud.pyw`
- Test: `tests/test_smoke_hud.py`

**Interfaces:**
- Consumes: `winkit.nowplaying` (`read`, `advance`, `progress_fraction`, `format_track`, `NowPlaying`); existing `Hud._fit_px`, `Hud._relayout_header`, `Hud.tick`, `Hud.close`, `Hud._draw_feeds`.
- Produces (on `Hud`): `self._np_title`, `self._np_bar_bg`, `self._np_bar` (canvas item ids); `self._np_bar_y` (int); `self._np_latest` (NowPlaying|None), `self._np_lock` (Lock), `self._np_stop` (Event), `self._np_thread`; methods `_start_nowplaying(self)` and `_draw_nowplaying(self)`.

**Relative layout note (earlier Round-2 features may have already shifted the
header rows/HEIGHT — apply these edits relative to whatever is currently there,
never against absolute line numbers or a hard-coded total HEIGHT):**
The media row keeps its position. Insert a `NOWPLAYING_H`-tall band directly
below the media row band; the now-playing title + progress bar live in it. Add
`+ NOWPLAYING_H` to: (a) the `HEIGHT` constant expression, (b) the clock/expand
row `y` expression **everywhere it is computed** (in `__init__` and in
`_relayout_header`), and (c) the feed-column top `y` expression in
`_draw_feeds`. Anchor the now-playing band to the media row center via
`ymedia + ROW_H // 2` (its band bottom) so it stays correct regardless of which
row index the media row currently occupies.

### Steps

- [ ] Step: write the failing test — append this class to `tests/test_smoke_hud.py`
(before the final `if __name__ == "__main__":` block):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudNowPlaying(_HudTestBase):
    def _sample(self, title="Song", artist="Artist", status="playing",
                position_s=30.0, duration_s=120.0):
        import time
        import winkit.nowplaying as nowplaying
        return nowplaying.NowPlaying(title, artist, status, position_s,
                                     duration_s, time.monotonic())

    def test_np_items_exist_and_blank_initially(self):
        root, hud = self._make_hud([])
        try:
            self.assertEqual(hud.canvas.itemcget(hud._np_title, "text"), "")
            x0, _y0, x1, _y1 = hud.canvas.coords(hud._np_bar)
            self.assertEqual(x0, x1)                       # zero width => blank
        finally:
            hud.close(); root.destroy()

    def test_np_renders_title_and_bar_when_playing(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            with hud._np_lock:
                hud._np_latest = self._sample(position_s=60.0, duration_s=120.0)
            hud._draw_nowplaying()
            text = hud.canvas.itemcget(hud._np_title, "text")
            self.assertIn("Song", text)
            self.assertIn("Artist", text)
            x0, _y0, x1, _y1 = hud.canvas.coords(hud._np_bar)
            self.assertGreater(x1 - x0, 0)                 # filled to ~half
            self.assertEqual(hud.canvas.itemcget(hud._np_bar, "fill"), hudmod.ACCENT)
        finally:
            hud.close(); root.destroy()

    def test_np_blank_when_stopped(self):
        root, hud = self._make_hud([])
        try:
            with hud._np_lock:
                hud._np_latest = self._sample(status="stopped")
            hud._draw_nowplaying()
            self.assertEqual(hud.canvas.itemcget(hud._np_title, "text"), "")
            x0, _y0, x1, _y1 = hud.canvas.coords(hud._np_bar)
            self.assertEqual(x0, x1)
        finally:
            hud.close(); root.destroy()

    def test_layout_reserved_and_stable_across_playback(self):
        root, hud = self._make_hud([])
        try:
            clock_y = hud.canvas.coords(hud._clock_text)[1]
            media_y = hud.canvas.coords(hud._media_play)[1]
            np_y = hud.canvas.coords(hud._np_title)[1]
            self.assertLess(media_y, np_y)                 # now-playing below media
            self.assertLess(np_y, clock_y)                 # ...and above the clock
            with hud._np_lock:
                hud._np_latest = self._sample()
            hud._draw_nowplaying()
            self.assertEqual(hud.canvas.coords(hud._clock_text)[1], clock_y)  # no jump
            with hud._np_lock:
                hud._np_latest = None
            hud._draw_nowplaying()
            self.assertEqual(hud.canvas.coords(hud._clock_text)[1], clock_y)  # still no jump
        finally:
            hud.close(); root.destroy()

    def test_np_recenters_when_widened(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            hud._toggle_width(); root.update_idletasks()
            self.assertEqual(hud.canvas.coords(hud._np_title)[0], hudmod.WIDTH_WIDE // 2)
        finally:
            hud.close(); root.destroy()

    def test_feeds_start_below_nowplaying_band(self):
        root, hud = self._make_hud([])
        try:
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("Global"))  # tab bar drew (feeds below np)
            self.assertLess(hud.canvas.coords(hud._np_title)[1],
                            hud.canvas.coords(hud._clock_text)[1])
        finally:
            hud.close(); root.destroy()
```

- [ ] Step: run it, expect FAIL — the HUD has no now-playing items/methods yet.

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudNowPlaying -v
```

Expected failure: `AttributeError: 'Hud' object has no attribute '_np_title'`
(and `_np_lock` / `_draw_nowplaying`).

- [ ] Step: implement — make the following edits to `hud.pyw`.

1) Add the poll-thread import. After the existing `import time` line near the top
(currently line ~11), add `threading`:

```python
import collections
import threading
import time
```

2) Add the module import next to the other `winkit`/`feedkit` imports (after
`import winkit.media as media`):

```python
import winkit.media as media
import winkit.nowplaying as nowplaying
```

3) Define the reserved-height constant BEFORE `HEIGHT` (it is used in the
`HEIGHT` expression). Immediately after the `WIDTH = 220` line, add:

```python
NOWPLAYING_H = 20      # reserved band under the media row: title line + progress bar
NP_BAR_H = 3           # progress-bar thickness (px)
```

4) Append `+ NOWPLAYING_H` to the `HEIGHT` constant expression. Current tree:

```python
HEIGHT = 134          # 5 header rows (CPU/RAM/GPU/media/clock) + margin
```

becomes (add the term to whatever base is present; if an earlier feature already
changed this line, append `+ NOWPLAYING_H` to that expression):

```python
HEIGHT = 134 + NOWPLAYING_H   # header rows + reserved now-playing band + margin
```

5) Add now-playing styling constants after the `MEDIA_NEXT = "..."` block:

```python
NP_TITLE_FONT = ("Consolas", 9)
NP_TRACK = "#2b2b34"   # progress-bar track (unfilled) colour
NP_POLL_S = 2.5        # background SMTC read interval (seconds)
```

6) Shift the clock/expand row down by `NOWPLAYING_H` in `__init__`. Current tree:

```python
        y3 = PAD + 4 * ROW_H + ROW_H // 2        # clock + expand: row 5 (under the media controls)
```

becomes (append `+ NOWPLAYING_H` to the existing clock-row expression, whatever
its multiplier is after earlier features):

```python
        y3 = PAD + 4 * ROW_H + ROW_H // 2 + NOWPLAYING_H   # clock + expand, shifted below the now-playing band
```

7) Create the persistent now-playing items. Immediately AFTER the media block in
`__init__` (after the `self._media_hits = [ ... ]` list literal, currently ending
~line 194), add:

```python
        # Now-playing band: reserved directly below the media row so the header
        # never jumps when playback starts/stops.
        np_top = ymedia + ROW_H // 2                 # bottom edge of the media row band
        self._np_bar_y = np_top + NOWPLAYING_H - NP_BAR_H - 1
        self._np_title = c.create_text(self.width // 2, np_top + 6, anchor="center",
                                       text="", fill=DIM, font=NP_TITLE_FONT)
        self._np_bar_bg = c.create_rectangle(PAD, self._np_bar_y, self.width - PAD,
                                             self._np_bar_y + NP_BAR_H,
                                             fill=NP_TRACK, outline="")
        self._np_bar = c.create_rectangle(PAD, self._np_bar_y, PAD,
                                          self._np_bar_y + NP_BAR_H,
                                          fill=ACCENT, outline="")
        self._np_lock = threading.Lock()
        self._np_latest = None                       # NowPlaying or None (poll thread writes)
        self._np_stop = threading.Event()
        self._np_thread = None
```

8) Start the poll thread where the manager starts. Current tree:

```python
        if not _smoke_ms():
            self.manager.start()   # no worker / no network under smoke launches
```

becomes:

```python
        if not _smoke_ms():
            self.manager.start()   # no worker / no network under smoke launches
            self._start_nowplaying()
```

9) Draw the now-playing band each tick. In `tick`, after `self._draw()`:

```python
        self._draw()
        self._draw_nowplaying()
```

10) Append `+ NOWPLAYING_H` to the feed-column top in `_draw_feeds`. Current tree:

```python
        y = PAD + 5 * ROW_H + 4                   # below the 5-row header (CPU/RAM/GPU/media/clock)
```

becomes (append the term to whatever top-of-feeds expression is present):

```python
        y = PAD + 5 * ROW_H + 4 + NOWPLAYING_H    # below the header rows + reserved now-playing band
```

11) Recenter the now-playing items on width change. In `_relayout_header`, after
the clock recenter line (`c.coords(self._clock_text, cx, ...)`), add:

```python
        c.coords(self._np_title, cx, self.canvas.coords(self._np_title)[1])
        c.coords(self._np_bar_bg, PAD, self._np_bar_y, self.width - PAD, self._np_bar_y + NP_BAR_H)
```

Also append `+ NOWPLAYING_H` to the `y3` clock-row expression inside
`_relayout_header` so the persistent clock/expand relayout matches `__init__`.
Current tree:

```python
        y3 = PAD + 4 * ROW_H + ROW_H // 2        # clock + expand row 5 (under media)
```

becomes:

```python
        y3 = PAD + 4 * ROW_H + ROW_H // 2 + NOWPLAYING_H   # clock + expand, below the now-playing band
```

12) Add the poll-thread starter and the draw step as new methods on `Hud`
(place them next to `_draw` / `_update_spark`):

```python
    def _start_nowplaying(self):
        """Spawn the daemon that polls SMTC every NP_POLL_S and stores the latest
        sample under a lock. It waits one interval before the first read so a
        just-constructed HUD (and the tests) see a stable None until then."""
        def _loop():
            while not self._np_stop.wait(NP_POLL_S):
                try:
                    s = nowplaying.read()
                except Exception:
                    s = None
                with self._np_lock:
                    self._np_latest = s
        self._np_thread = threading.Thread(target=_loop, name="nowplaying",
                                            daemon=True)
        self._np_thread.start()

    def _draw_nowplaying(self):
        """Update the title line + progress bar from the latest SMTC sample,
        advancing the position with wall-clock so the bar moves smoothly between
        reads. Blank when nothing is playing. Never raises."""
        c = self.canvas
        with self._np_lock:
            s = self._np_latest
        left = PAD
        right = self.width - PAD
        y0, y1 = self._np_bar_y, self._np_bar_y + NP_BAR_H
        if s is None or s.status == "stopped":
            try:
                c.itemconfig(self._np_title, text="")
                c.coords(self._np_bar, left, y0, left, y1)   # zero width => blank
            except tk.TclError:
                pass
            return
        try:
            text = nowplaying.format_track(s.title, s.artist)
            c.itemconfig(self._np_title, text=self._fit_px(text, PAD) if text else "")
            pos = nowplaying.advance(s.position_s, time.monotonic() - s.sampled_at,
                                     s.status)
            frac = nowplaying.progress_fraction(pos, s.duration_s)
            c.coords(self._np_bar, left, y0, left + int((right - left) * frac), y1)
        except tk.TclError:
            pass
```

13) Stop the poll thread on close. In `close`, after the `self._stop_marquee()`
call, add:

```python
        self._stop_marquee()
        self._np_stop.set()
```

- [ ] Step: run it, expect PASS.

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudNowPlaying -v
```

- [ ] Step: run the existing HUD suites to confirm the layout shift did not
regress the media/expand/feed geometry tests.

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v
```

- [ ] Step: commit.

```
git add hud.pyw tests/test_smoke_hud.py
git commit -m "Render now-playing progress bar + track title under the media row

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

> **Marquee for the now-playing line (closes a spec-coverage gap).** Feature 2 of
> the design requires the persistent `title — artist` line to **marquee** when it
> is too long to fit — Task 3 above renders it static (and ellipsis-truncates a
> long title via `_fit_px`, an acceptable intermediate). Tasks 4–5 below add the
> real ticker: Task 4 factors the wrap math into a pure, shared stepper; Task 5
> **replaces** Task 3's title handling in `_draw_nowplaying` so a long line
> scrolls (and a short one still renders static/centered). The design's "reuse
> the existing marquee machinery" intent is honoured by having both the feed
> marquee and the now-playing ticker drive their offset through the same pure
> `marquee_step`.

---

## Task 4: Pure marquee helpers (shared wrap math)

Add two pure, fully unit-tested helpers to `winkit/nowplaying.py` that capture the
existing feed-marquee wrap math so both the feed marquee and the now-playing
ticker can share one implementation: `marquee_scroll_max` (decides scroll vs.
static from measured widths) and `marquee_step` (the non-bouncing offset
progression). No Tk, no HUD wiring yet — this is pure arithmetic.

**Files:**
- Modify: `winkit/nowplaying.py`
- Test: `tests/test_nowplaying.py`

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces:
  - `marquee_scroll_max(text_w, budget_w) -> int` — `max(0, text_w - budget_w)`;
    `0` means the text fits and should render **static** (no scrolling); a
    positive value is how many pixels the line must travel left to reveal its end.
    Bad input → `0`.
  - `marquee_step(offset, max_off, pause, step=2, end_pause=10) -> (int, int)` —
    one tick of a **wrap-style (non-bouncing)** marquee, returning
    `(offset, pause)`. `offset` climbs from `0` toward `max_off` by `step`,
    pauses `end_pause` frames at the end, then **jumps back to `0`** (never
    reverses). Returns `(0, 0)` (static) whenever `max_off <= 0`. This mirrors,
    exactly for `max_off > 0`, the arithmetic currently inlined in
    `Hud._marquee_step`.

### Steps

- [ ] Step: write the failing test — append these two classes to
`tests/test_nowplaying.py` (before the `if __name__ == "__main__":` block):

```python
class TestMarqueeScrollMax(unittest.TestCase):
    def test_fits_is_zero(self):
        self.assertEqual(nowplaying.marquee_scroll_max(100, 200), 0)

    def test_exact_fit_is_zero(self):
        self.assertEqual(nowplaying.marquee_scroll_max(200, 200), 0)

    def test_overflow_is_the_difference(self):
        self.assertEqual(nowplaying.marquee_scroll_max(260, 200), 60)

    def test_bad_input_is_zero(self):
        self.assertEqual(nowplaying.marquee_scroll_max(None, None), 0)


class TestMarqueeStep(unittest.TestCase):
    def test_static_when_max_not_positive(self):
        self.assertEqual(nowplaying.marquee_step(0, 0, 0), (0, 0))
        self.assertEqual(nowplaying.marquee_step(7, -3, 5), (0, 0))

    def test_advances_by_step_from_start(self):
        self.assertEqual(nowplaying.marquee_step(0, 100, 0), (2, 0))

    def test_custom_step(self):
        self.assertEqual(nowplaying.marquee_step(0, 100, 0, step=5), (5, 0))

    def test_clamps_at_end_and_arms_pause(self):
        self.assertEqual(nowplaying.marquee_step(99, 100, 0), (100, 10))

    def test_pause_counts_down_without_moving(self):
        self.assertEqual(nowplaying.marquee_step(100, 100, 10), (100, 9))

    def test_wraps_to_start_not_bounce(self):
        # At the end with the pause elapsed: JUMP to 0 (a bounce would give 98).
        self.assertEqual(nowplaying.marquee_step(100, 100, 0), (0, 10))

    def test_full_cycle_reaches_end_then_wraps_never_reverses(self):
        offset, pause, max_off = 0, 0, 20
        seen = []
        for _ in range(80):
            offset, pause = nowplaying.marquee_step(offset, max_off, pause)
            seen.append(offset)
        self.assertIn(max_off, seen)                      # scrolled to the end
        i = seen.index(max_off)
        j = i
        while j < len(seen) and seen[j] == max_off:
            j += 1                                        # skip the brief end pause
        self.assertLess(j, len(seen), "expected motion after the end pause")
        self.assertEqual(seen[j], 0)                      # wraps to start (bounce => 18)
        self.assertTrue(all(o >= 0 for o in seen))        # never runs backwards past 0
```

- [ ] Step: run it, expect FAIL — the helpers do not exist yet.

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_nowplaying.TestMarqueeScrollMax tests.test_nowplaying.TestMarqueeStep -v
```

Expected failure: `AttributeError: module 'winkit.nowplaying' has no attribute 'marquee_scroll_max'`.

- [ ] Step: implement — in `winkit/nowplaying.py`, insert the two functions
**immediately before** the WinRT section (anchor on the stable comment line
`# --- WinRT SMTC reader (guarded; never raises) ---`), so they sit with the
other pure helpers:

```python
def marquee_scroll_max(text_w, budget_w):
    """Pixels a line must scroll left to reveal its end: max(0, text_w - budget_w).
    0 means the text fits its budget and should render static (no scrolling)."""
    try:
        return max(0, int(text_w) - int(budget_w))
    except (TypeError, ValueError):
        return 0


def marquee_step(offset, max_off, pause, step=2, end_pause=10):
    """One tick of a wrap-style (non-bouncing) marquee. Returns (offset, pause).
    `offset` climbs 0 -> max_off by `step`, pauses `end_pause` frames at the end,
    then JUMPS back to 0 and repeats (it never reverses). Static (0, 0) whenever
    max_off <= 0. Mirrors, for max_off > 0, the math inlined in Hud._marquee_step
    so the feed marquee and the now-playing ticker share one wrap implementation."""
    if max_off <= 0:
        return 0, 0
    if pause > 0:
        return offset, pause - 1
    if offset >= max_off:
        return 0, end_pause                 # reached the end -> jump back to the start
    offset += step
    if offset >= max_off:
        return max_off, end_pause           # clamp at the end, pause, then wrap next tick
    return offset, 0
```

- [ ] Step: run it, expect PASS.

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_nowplaying -v
```

- [ ] Step: commit.

```
git add winkit/nowplaying.py tests/test_nowplaying.py
git commit -m "Add pure marquee helpers (marquee_scroll_max, marquee_step)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: HUD now-playing ticker (marquee the long title)

Make the persistent now-playing line scroll when it overflows. Replace the
`_draw_nowplaying` body from Task 3 so a long `title — artist` line renders with
its FULL text (no ellipsis) and auto-scrolls, while a line that fits renders
static and centered. Add a small pixel-motion loop `_np_marquee_step` (33 ms, the
same cadence and `step=2` as the feed marquee) driven by the pure
`nowplaying.marquee_step`, and refactor the existing feed `_marquee_step` to call
the same shared stepper so there is exactly one wrap-math implementation. The
title item switches to `anchor="w"` and is moved left by `base_x - offset` while
scrolling; overflow is hidden by the canvas widget edge, exactly as the feed
marquee already relies on.

**Files:**
- Modify: `hud.pyw`
- Test: `tests/test_smoke_hud.py`

**Interfaces:**
- Consumes: `winkit.nowplaying` (`marquee_scroll_max`, `marquee_step`,
  `format_track`, `advance`, `progress_fraction`); existing `Hud._np_title`,
  `Hud._np_bar`, `Hud._np_bar_y`, `Hud._np_lock`, `Hud._np_latest`,
  `Hud._feed_font_measure` (Consolas 9 — same size as `NP_TITLE_FONT`, so it
  measures the title correctly); existing feed marquee `Hud._marquee_step`.
- Produces (on `Hud`): `self._np_scroll` (dict `{text, offset, pause, max,
  base_x}` while scrolling, else `None`); `self._np_marquee_after` (pending
  after() id or `None`); methods `_np_marquee_ensure(self)` and
  `_np_marquee_step(self)`; a rewritten `_draw_nowplaying(self)`; and a
  `_marquee_step(self)` refactored to delegate its wrap math to
  `nowplaying.marquee_step`.

**Relative edit note (Round-2 features and Task 3 may have shifted rows/HEIGHT —
anchor every edit on the stable code text quoted below, never on line numbers):**
all four edits attach to text that is stable regardless of header-row offsets.

### Steps

- [ ] Step: write the failing test — append this class to `tests/test_smoke_hud.py`
(before the final `if __name__ == "__main__":` block):

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudNowPlayingMarquee(_HudTestBase):
    LONG = "A tremendously long now-playing track title that will never fit"
    ARTIST = "An Equally Long Artist Name Goes Right Here"

    def _sample(self, title, artist=ARTIST, status="playing",
                position_s=30.0, duration_s=120.0):
        import time
        import winkit.nowplaying as nowplaying
        return nowplaying.NowPlaying(title, artist, status, position_s,
                                     duration_s, time.monotonic())

    def test_short_title_is_static_and_centered(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            with hud._np_lock:
                hud._np_latest = self._sample("Hi", artist="X")
            hud._draw_nowplaying()
            self.assertIsNone(hud._np_scroll)                       # fits => no scrolling
            self.assertEqual(hud.canvas.coords(hud._np_title)[0], hudmod.WIDTH // 2)
            self.assertEqual(hud.canvas.itemcget(hud._np_title, "anchor"), "center")
        finally:
            hud.close(); root.destroy()

    def test_long_title_shows_full_text_and_scrolls_left(self):
        import winkit.nowplaying as nowplaying
        root, hud = self._make_hud([])
        try:
            with hud._np_lock:
                hud._np_latest = self._sample(self.LONG)
            hud._draw_nowplaying()
            self.assertIsNotNone(hud._np_scroll)                    # overflow => scroll
            self.assertGreater(hud._np_scroll["max"], 0)
            shown = hud.canvas.itemcget(hud._np_title, "text")
            self.assertEqual(shown, nowplaying.format_track(self.LONG, self.ARTIST))
            self.assertNotIn("…", shown)                            # full text, not ellipsized
            x_before = hud.canvas.coords(hud._np_title)[0]
            for _ in range(6):
                hud._np_marquee_step()
            x_after = hud.canvas.coords(hud._np_title)[0]
            self.assertLess(x_after, x_before)                      # scrolled left by pixels
        finally:
            hud.close(); root.destroy()

    def test_long_title_wraps_to_start_not_bounce(self):
        root, hud = self._make_hud([])
        try:
            with hud._np_lock:
                hud._np_latest = self._sample(self.LONG)
            hud._draw_nowplaying()
            m = hud._np_scroll
            offsets = []
            for _ in range(m["max"] // 2 + 60):
                hud._np_marquee_step()
                offsets.append(hud._np_scroll["offset"])
            self.assertIn(m["max"], offsets)                        # scrolled to the end
            i = offsets.index(m["max"])
            j = i
            while j < len(offsets) and offsets[j] == m["max"]:
                j += 1                                              # skip the end pause
            self.assertLess(j, len(offsets), "expected motion after the end pause")
            self.assertEqual(offsets[j], 0)                         # wraps to start, not bounce
        finally:
            hud.close(); root.destroy()

    def test_switch_long_to_short_returns_to_static(self):
        import hud as hudmod
        root, hud = self._make_hud([])
        try:
            with hud._np_lock:
                hud._np_latest = self._sample(self.LONG)
            hud._draw_nowplaying()
            self.assertIsNotNone(hud._np_scroll)
            with hud._np_lock:
                hud._np_latest = self._sample("Hi", artist="X")
            hud._draw_nowplaying()
            self.assertIsNone(hud._np_scroll)                       # back to static
            self.assertEqual(hud.canvas.coords(hud._np_title)[0], hudmod.WIDTH // 2)
        finally:
            hud.close(); root.destroy()

    def test_stopped_clears_scroll_state(self):
        root, hud = self._make_hud([])
        try:
            with hud._np_lock:
                hud._np_latest = self._sample(self.LONG)
            hud._draw_nowplaying()
            self.assertIsNotNone(hud._np_scroll)
            with hud._np_lock:
                hud._np_latest = self._sample(self.LONG, status="stopped")
            hud._draw_nowplaying()
            self.assertIsNone(hud._np_scroll)                       # stopped => no ticker
            self.assertEqual(hud.canvas.itemcget(hud._np_title, "text"), "")
        finally:
            hud.close(); root.destroy()
```

- [ ] Step: run it, expect FAIL — the ticker state/methods do not exist yet.

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudNowPlayingMarquee -v
```

Expected failure: `AttributeError: 'Hud' object has no attribute '_np_scroll'`
(and `_np_marquee_step`).

- [ ] Step: implement — make the following four edits to `hud.pyw`.

**(1) Add the ticker state fields in `__init__`.** Directly after the
`self._np_thread = None` line (added in Task 3), add:

```python
        self._np_thread = None
        self._np_scroll = None            # now-playing title ticker state, or None (fits/blank)
        self._np_marquee_after = None     # pending after() id for the ticker loop
```

**(2) Refactor the feed `_marquee_step` to delegate to the shared stepper** so the
feed marquee and the now-playing ticker share one wrap-math implementation.
Replace the existing method (anchor on `def _marquee_step(self):`) with:

```python
    def _marquee_step(self):
        m = self._marquee
        if m is None:
            return
        try:
            m["offset"], m["pause"] = nowplaying.marquee_step(
                m["offset"], m["max"], m["pause"])   # shared wrap math (0->max->0, no bounce)
            y = self.canvas.coords(m["item"])[1]
            self.canvas.coords(m["item"], m["base_x"] - m["offset"], y)
        except tk.TclError:
            self._stop_marquee(); return
        self._marquee_after = self.root.after(33, self._marquee_step)
```

This is behaviour-preserving for the feed: a hovered truncated line always has
`max > 0`, and for `max > 0` `nowplaying.marquee_step` reproduces the old inline
arithmetic exactly (climb by 2, 10-frame end pause, jump to 0). The existing
`TestHudMarquee` tests re-verify this in the full-suite run below.

**(3) Replace `_draw_nowplaying` (from Task 3) and add the ticker methods.**
Replace the whole `_draw_nowplaying` method with the version below, then add
`_np_marquee_ensure` and `_np_marquee_step` immediately after it:

```python
    def _draw_nowplaying(self):
        """Update the title line + progress bar from the latest SMTC sample. The
        bar advances with wall-clock so it moves smoothly between reads. A title
        that fits renders static and centered; a title that overflows the tile
        auto-scrolls (music-player ticker: scroll left to reveal the end, then
        jump back to the start -- never bouncing). Blank when nothing is playing.
        Never raises."""
        c = self.canvas
        with self._np_lock:
            s = self._np_latest
        left = PAD
        right = self.width - PAD
        y0, y1 = self._np_bar_y, self._np_bar_y + NP_BAR_H
        try:
            title_y = self.canvas.coords(self._np_title)[1]
            if s is None or s.status == "stopped":
                self._np_scroll = None                       # nothing playing -> no ticker
                c.itemconfig(self._np_title, text="", anchor="center")
                c.coords(self._np_title, self.width // 2, title_y)
                c.coords(self._np_bar, left, y0, left, y1)   # zero width => blank
                return
            text = nowplaying.format_track(s.title, s.artist)
            pos = nowplaying.advance(s.position_s, time.monotonic() - s.sampled_at,
                                     s.status)
            frac = nowplaying.progress_fraction(pos, s.duration_s)
            c.coords(self._np_bar, left, y0, left + int((right - left) * frac), y1)
            c.itemconfig(self._np_title, text=text)          # FULL text; the widget edge clips overflow
            max_off = nowplaying.marquee_scroll_max(
                self._feed_font_measure.measure(text), right - left)
            if max_off <= 0:
                self._np_scroll = None                       # fits => static, centered
                c.itemconfig(self._np_title, anchor="center")
                c.coords(self._np_title, self.width // 2, title_y)
            else:
                if self._np_scroll is None or self._np_scroll.get("text") != text:
                    self._np_scroll = {"text": text, "offset": 0, "pause": 0}
                self._np_scroll["max"] = max_off
                self._np_scroll["base_x"] = left
                c.itemconfig(self._np_title, anchor="w")
                c.coords(self._np_title, left - self._np_scroll["offset"], title_y)
                self._np_marquee_ensure()                    # kick the ticker loop if idle
        except tk.TclError:
            pass

    def _np_marquee_ensure(self):
        """Start the now-playing ticker loop if it is not already scheduled. The
        loop self-stops when _np_scroll goes None (title fits or nothing plays)."""
        if self._np_marquee_after is None:
            self._np_marquee_after = self.root.after(33, self._np_marquee_step)

    def _np_marquee_step(self):
        """Advance the persistent now-playing title one pixel-motion tick using the
        SAME wrap math as the feed marquee (nowplaying.marquee_step). Runs only
        while a long title overflows; stops itself otherwise. Never raises."""
        m = self._np_scroll
        if m is None:
            self._np_marquee_after = None                    # nothing to scroll -> stop the loop
            return
        try:
            m["offset"], m["pause"] = nowplaying.marquee_step(
                m["offset"], m["max"], m["pause"])
            y = self.canvas.coords(self._np_title)[1]
            self.canvas.coords(self._np_title, m["base_x"] - m["offset"], y)
        except tk.TclError:
            self._np_marquee_after = None
            return
        self._np_marquee_after = self.root.after(33, self._np_marquee_step)
```

`_draw_nowplaying` is the source of truth: it re-measures and re-lays-out the
title every tick, so the `_relayout_header` recenter (Task 3) on a width toggle is
a harmless transient — the next tick re-evaluates scroll-vs-static at the new
width. Because `_np_measure`/`NP_TITLE_FONT` is Consolas 9, the existing
`self._feed_font_measure` (also Consolas 9) measures the title correctly; no new
font object is needed.

**(4) Stop the ticker loop on close.** In `close`, directly after the
`self._np_stop.set()` line (added in Task 3), add:

```python
        self._np_stop.set()
        if self._np_marquee_after is not None:
            try:
                self.root.after_cancel(self._np_marquee_after)
            except Exception:
                pass
            self._np_marquee_after = None
```

- [ ] Step: run it, expect PASS.

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudNowPlayingMarquee -v
```

- [ ] Step: run the existing marquee + now-playing suites to confirm the shared
stepper refactor did not regress the feed marquee or the Task 3 render tests.

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudMarquee tests.test_smoke_hud.TestHudNowPlaying -v
```

- [ ] Step: commit.

```
git add hud.pyw tests/test_smoke_hud.py
git commit -m "Marquee-scroll the now-playing title when it overflows the tile

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
