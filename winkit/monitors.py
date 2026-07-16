"""Monitor enumeration: per-monitor bounds, work areas, and device names.

Coordinates are physical pixels (the toys enable per-monitor-v2 DPI awareness
before Tk starts). HMONITOR is pointer-sized — typed c_void_p throughout, per
the 64-bit rules in docs/superpowers/specs/2026-06-24-native-gotchas.md.
"""
import ctypes
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)

MONITORINFOF_PRIMARY = 0x1
MONITOR_DEFAULTTONEAREST = 0x2

_CCHDEVICENAME = 32


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * _CCHDEVICENAME),
    ]


_MonitorEnumProc = ctypes.WINFUNCTYPE(
    wintypes.BOOL, ctypes.c_void_p, wintypes.HDC,
    ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

_user32.EnumDisplayMonitors.restype = wintypes.BOOL
_user32.EnumDisplayMonitors.argtypes = [
    wintypes.HDC, ctypes.POINTER(wintypes.RECT), _MonitorEnumProc, wintypes.LPARAM]
_user32.GetMonitorInfoW.restype = wintypes.BOOL
_user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MONITORINFOEXW)]
_user32.MonitorFromPoint.restype = ctypes.c_void_p
_user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]


def _rect_tuple(rc):
    return (rc.left, rc.top, rc.right, rc.bottom)


def _info_for(hmonitor):
    info = _MONITORINFOEXW()
    info.cbSize = ctypes.sizeof(_MONITORINFOEXW)
    if not _user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
        return None
    return {
        "handle": int(hmonitor or 0),
        "device": info.szDevice,
        "rect": _rect_tuple(info.rcMonitor),
        "work": _rect_tuple(info.rcWork),
        "primary": bool(info.dwFlags & MONITORINFOF_PRIMARY),
    }


def list_monitors():
    """All attached monitors as dicts: handle, device (e.g. r'\\\\.\\DISPLAY1'),
    rect, work (both (l, t, r, b) physical px), primary. Primary sorts first,
    then by device name, so ordering is stable across calls."""
    found = []

    def _cb(hmon, hdc, lprc, lparam):
        info = _info_for(hmon)
        if info:
            found.append(info)
        return True

    # The callback ref only needs to outlive this synchronous call.
    _user32.EnumDisplayMonitors(None, None, _MonitorEnumProc(_cb), 0)
    found.sort(key=lambda m: (not m["primary"], m["device"]))
    return found


def monitor_at(x, y):
    """The monitor containing (or nearest to) screen point (x, y), same dict
    shape as list_monitors(); None only if the API fails outright."""
    hmon = _user32.MonitorFromPoint(wintypes.POINT(x, y), MONITOR_DEFAULTTONEAREST)
    return _info_for(hmon) if hmon else None
