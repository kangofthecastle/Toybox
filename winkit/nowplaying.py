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


def format_clock(seconds):
    """A media-player time stamp: 'M:SS', or 'H:MM:SS' once past an hour. Seconds
    are truncated (83.9 -> '1:23'); negatives and non-numbers render '0:00'."""
    try:
        total = int(float(seconds))
    except (TypeError, ValueError):
        return "0:00"
    if total < 0:
        total = 0
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%d:%02d:%02d" % (h, m, s)
    return "%d:%02d" % (m, s)


def seek_target_seconds(x, bar_left, bar_right, duration_s):
    """Seconds to seek to for a click at pixel `x` on a progress bar spanning
    [bar_left, bar_right]. The fraction is clamped to [0, 1], so clicks past
    either end pin to 0/duration. Returns 0.0 for a non-positive duration, a
    degenerate span, or any non-numeric input. NEVER raises."""
    try:
        d = float(duration_s)
        left = float(bar_left)
        right = float(bar_right)
        px = float(x)
    except (TypeError, ValueError):
        return 0.0
    if d <= 0 or right <= left:
        return 0.0
    frac = (px - left) / (right - left)
    if frac <= 0:
        return 0.0
    if frac >= 1:
        return d
    return frac * d


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


def seek(position_s):
    """Best-effort seek of the active SMTC session to `position_s` seconds.
    Returns True if the change-position request was dispatched, else False.
    NEVER raises. A source without a seekable timeline (e.g. foobar2000) just
    returns without effect -- the HUD only offers seeking when duration > 0."""
    try:
        return _seek_impl(position_s)
    except Exception:
        return False


def _change_position(session, ticks):
    """Call session vtable slot 23 -- TryChangePlaybackPositionAsync(Int64 ticks,
    out IAsyncOperation<bool>**). The slot follows the same live-anchored ABI as
    read()'s 6-9 (get_SourceAppUserModelId(6) .. GetPlaybackInfo(9), then the
    Try* methods run 10..; ChangePlaybackPosition is the 14th Try*). A wrong slot
    access-violates -- caught by seek()'s blanket except -- so this cannot be
    unit-tested without a seekable session. Returns (hresult, op_pointer)."""
    vtbl = ctypes.cast(session, ctypes.POINTER(ctypes.c_void_p))[0]
    fn_addr = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[23]
    proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p,
                               ctypes.c_int64, ctypes.c_void_p)
    op = ctypes.c_void_p()
    hr = proto(fn_addr)(session, ctypes.c_int64(ticks), ctypes.byref(op))
    return hr, op


def _seek_impl(position_s):
    ticks = int(max(0.0, float(position_s)) * _TICKS_PER_S)
    combase = ctypes.WinDLL("combase.dll")
    combase.WindowsCreateString.argtypes = [
        ctypes.c_wchar_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    combase.WindowsDeleteString.argtypes = [ctypes.c_void_p]
    combase.RoInitialize.argtypes = [ctypes.c_int]
    combase.RoGetActivationFactory.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    combase.RoInitialize(_RO_INIT_MULTITHREADED)   # RPC_E_CHANGED_MODE is fine

    cls = ctypes.c_void_p()
    if combase.WindowsCreateString(_MANAGER_CLASS, len(_MANAGER_CLASS),
                                   ctypes.byref(cls)) != 0 or not cls.value:
        return False
    factory = ctypes.c_void_p()
    manager = ctypes.c_void_p()
    session = ctypes.c_void_p()
    info = ctypes.c_void_p()
    op = None
    try:
        iid = _guid(_IID_MANAGER_STATICS)
        if combase.RoGetActivationFactory(
                cls, ctypes.byref(iid), ctypes.byref(factory)) != 0 or not factory.value:
            return False
        rop = ctypes.c_void_p()
        if _vcall(factory, 6, ctypes.byref(rop)) != 0 or not rop.value:
            return False
        try:
            manager = _await(rop, time.monotonic() + 1.0)
        finally:
            _release(rop)
        if not manager or not manager.value:
            return False
        if _vcall(manager, 6, ctypes.byref(session)) != 0 or not session.value:
            return False
        hr, op = _change_position(session, ticks)
        if hr != 0 or not op or not op.value:
            return False
        # Drive the async to completion (bounded) so the seek is actually issued;
        # the bool result is ignored -- dispatch is all the HUD needs.
        iid2 = _guid(_IID_ASYNC_INFO)
        if _vcall(op, 0, ctypes.byref(iid2), ctypes.byref(info)) == 0 and info.value:
            deadline = time.monotonic() + 1.0
            status = ctypes.c_int(_ASYNC_STARTED)
            while time.monotonic() < deadline:
                if _vcall(info, 7, ctypes.byref(status)) != 0 or status.value != _ASYNC_STARTED:
                    break
                time.sleep(0.01)
        return True
    finally:
        combase.WindowsDeleteString(cls)
        _release(info)
        if op:
            _release(op)
        for p in (session, manager, factory):
            _release(p)


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
    albumartist_h = ctypes.c_void_p()
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

        # Session vtable (after IUnknown+IInspectable = slots 0-5):
        #   6 get_SourceAppUserModelId, 7 TryGetMediaPropertiesAsync,
        #   8 GetTimelineProperties, 9 GetPlaybackInfo.
        # Slots verified against a live SMTC session -- a wrong slot here
        # access-violates (which read()'s blanket except then hides as None),
        # so these cannot be unit-tested without real playback.

        # Media properties FIRST (title/artist), so a source that publishes no
        # timeline still yields the track.
        title = artist = ""
        mop = ctypes.c_void_p()
        if _vcall(session, 7, ctypes.byref(mop)) == 0 and mop.value:
            try:
                props = _await(mop, time.monotonic() + 1.0)
            finally:
                _release(mop)
            if props and props.value:
                if _vcall(props, 6, ctypes.byref(title_h)) == 0:            # get_Title
                    title = _hstring_to_str(combase, title_h)
                if _vcall(props, 8, ctypes.byref(artist_h)) == 0:           # get_Artist
                    artist = _hstring_to_str(combase, artist_h)
                if not artist and _vcall(props, 9, ctypes.byref(albumartist_h)) == 0:
                    artist = _hstring_to_str(combase, albumartist_h)        # AlbumArtist fallback

        # Timeline (start/end/position). Many sources (e.g. foobar2000) report
        # all zeros; duration_s == 0 then means "no seekable timeline".
        start_s = end_s = position_s = 0.0
        if _vcall(session, 8, ctypes.byref(timeline)) == 0 and timeline.value:
            start_s = _timespan_s(timeline, 6)      # get_StartTime
            end_s = _timespan_s(timeline, 7)        # get_EndTime
            position_s = _timespan_s(timeline, 10)  # get_Position
        duration_s = end_s - start_s if end_s > start_s else 0.0
        position_s = max(0.0, position_s - start_s)

        status = "stopped"
        if _vcall(session, 9, ctypes.byref(playback)) == 0 and playback.value:
            pstatus = ctypes.c_int(0)
            if _vcall(playback, 7, ctypes.byref(pstatus)) == 0:            # get_PlaybackStatus
                if pstatus.value == _STATUS_PLAYING:
                    status = "playing"
                elif pstatus.value == _STATUS_PAUSED:
                    status = "paused"

        return NowPlaying(title, artist, status, position_s, duration_s,
                          time.monotonic())
    finally:
        combase.WindowsDeleteString(cls)
        for h in (title_h, artist_h, albumartist_h):
            try:
                combase.WindowsDeleteString(h)
            except Exception:
                pass
        for p in (props, playback, timeline, session, manager, factory):
            _release(p)
