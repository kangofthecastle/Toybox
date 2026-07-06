"""Master-volume control for the default Windows playback (render) endpoint via
Core Audio (IAudioEndpointVolume) through ctypes. get()/set_level()/set_mute()/
toggle_mute() are blanket-guarded and NEVER raise on any machine (no device, COM
error, non-Windows). Also holds the pure UI-math helpers the HUD slider uses.
Pure Python 3.12 stdlib -- no pip."""


def clamp01(x):
    """x coerced into [0.0, 1.0]; 0.0 on bad input."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if v <= 0.0:
        return 0.0
    if v >= 1.0:
        return 1.0
    return v


def level_from_x(x, x_left, x_right):
    """Fraction in [0,1] for a click/drag at pixel x on a track spanning
    [x_left, x_right]. 0.0 for a degenerate/backwards track or bad input."""
    try:
        x = float(x); lo = float(x_left); hi = float(x_right)
    except (TypeError, ValueError):
        return 0.0
    if hi <= lo:
        return 0.0
    return clamp01((x - lo) / (hi - lo))


def x_from_level(level, x_left, x_right):
    """Knob pixel-x for `level` on a track spanning [x_left, x_right]."""
    try:
        lo = int(x_left); hi = int(x_right)
    except (TypeError, ValueError):
        return 0
    return lo + int((hi - lo) * clamp01(level))


def format_pct(level):
    """'63%' for a level; '' for None."""
    if level is None:
        return ""
    return "%d%%" % round(clamp01(level) * 100)


def step_level(level, delta):
    """level + delta, clamped to [0,1]."""
    try:
        base = float(level)
    except (TypeError, ValueError):
        base = 0.0
    try:
        d = float(delta)
    except (TypeError, ValueError):
        d = 0.0
    return clamp01(base + d)


# --- Core Audio (IAudioEndpointVolume) via ctypes; guarded, never raises ---
import ctypes

_CLSID_ENUM = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"   # MMDeviceEnumerator
_IID_ENUM = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"      # IMMDeviceEnumerator
_IID_EPV = "{5CDF2C82-841E-4546-9722-0CF74078229A}"       # IAudioEndpointVolume
_CLSCTX_ALL = 0x17
_COINIT_MTA = 0x0
_ERENDER = 0
_ECONSOLE = 0


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort),
                ("Data3", ctypes.c_ushort), ("Data4", ctypes.c_ubyte * 8)]


def _guid(text):
    g = _GUID()
    if ctypes.WinDLL("ole32").CLSIDFromString(ctypes.c_wchar_p(text),
                                              ctypes.byref(g)) != 0:
        raise OSError("bad guid")
    return g


def _call(ptr, slot, restype, argtypes, *args):
    """Invoke COM vtable method `slot` on interface pointer `ptr`."""
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    fn = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[slot]
    proto = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)
    return proto(fn)(ptr, *args)


def _release(ptr):
    try:
        if ptr and ptr.value:
            _call(ptr, 2, ctypes.c_ulong, [])   # IUnknown::Release
    except Exception:
        pass


def _with_epv(fn):
    """Acquire the default render endpoint's IAudioEndpointVolume, run fn(epv),
    release everything, and balance COM init. Returns fn's result or None. Never
    raises."""
    try:
        ole32 = ctypes.WinDLL("ole32")
    except Exception:
        return None
    hr = ole32.CoInitializeEx(None, _COINIT_MTA)
    need_uninit = hr in (0, 1)          # S_OK / S_FALSE -> we own an init to undo
    enum = ctypes.c_void_p()
    device = ctypes.c_void_p()
    epv = ctypes.c_void_p()
    try:
        clsid = _guid(_CLSID_ENUM)
        iid_enum = _guid(_IID_ENUM)
        iid_epv = _guid(_IID_EPV)
        ole32.CoCreateInstance.argtypes = [
            ctypes.POINTER(_GUID), ctypes.c_void_p, ctypes.c_uint,
            ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p)]
        if ole32.CoCreateInstance(ctypes.byref(clsid), None, _CLSCTX_ALL,
                                  ctypes.byref(iid_enum), ctypes.byref(enum)) != 0 \
                or not enum.value:
            return None
        if _call(enum, 4, ctypes.c_long,
                 [ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)],
                 _ERENDER, _ECONSOLE, ctypes.byref(device)) != 0 or not device.value:
            return None
        if _call(device, 3, ctypes.c_long,
                 [ctypes.POINTER(_GUID), ctypes.c_uint, ctypes.c_void_p,
                  ctypes.POINTER(ctypes.c_void_p)],
                 ctypes.byref(iid_epv), _CLSCTX_ALL, None,
                 ctypes.byref(epv)) != 0 or not epv.value:
            return None
        return fn(epv)
    except Exception:
        return None
    finally:
        for p in (epv, device, enum):
            _release(p)
        if need_uninit:
            try:
                ole32.CoUninitialize()
            except Exception:
                pass


def get():
    """(level in [0,1], muted bool) for the default playback device, or None."""
    def _read(epv):
        lvl = ctypes.c_float(0.0)
        mute = ctypes.c_int(0)
        if _call(epv, 9, ctypes.c_long, [ctypes.POINTER(ctypes.c_float)],
                 ctypes.byref(lvl)) != 0:
            return None
        if _call(epv, 15, ctypes.c_long, [ctypes.POINTER(ctypes.c_int)],
                 ctypes.byref(mute)) != 0:
            return None
        return (clamp01(lvl.value), bool(mute.value))
    return _with_epv(_read)


def set_level(frac):
    """Set the master scalar to `frac` (0..1). Rejects non-numeric input without
    touching COM. Returns True on a completed write attempt, else False."""
    try:
        f = float(frac)
    except (TypeError, ValueError):
        return False
    f = clamp01(f)

    def _write(epv):
        return _call(epv, 7, ctypes.c_long, [ctypes.c_float, ctypes.c_void_p],
                     ctypes.c_float(f), None) == 0
    return bool(_with_epv(_write))


def set_mute(mute):
    """Set mute to bool(mute). Returns True on a completed write, else False."""
    b = 1 if mute else 0

    def _write(epv):
        return _call(epv, 14, ctypes.c_long, [ctypes.c_int, ctypes.c_void_p],
                     b, None) == 0
    return bool(_with_epv(_write))


def toggle_mute():
    """Flip the current mute state. Returns the new state, or None if unreadable."""
    cur = get()
    if cur is None:
        return None
    new = not cur[1]
    set_mute(new)
    return new
