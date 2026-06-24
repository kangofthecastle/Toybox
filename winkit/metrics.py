"""System metrics: CPU busy% (GetSystemTimes) and RAM load% (GlobalMemoryStatusEx)."""
import ctypes
from ctypes import wintypes

import sysmetrics

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


_kernel32.GetSystemTimes.restype = wintypes.BOOL
_kernel32.GetSystemTimes.argtypes = [ctypes.POINTER(_FILETIME)] * 3


def _ticks(ft):
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def _read_times():
    idle, kernel, user = _FILETIME(), _FILETIME(), _FILETIME()
    if not _kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        raise ctypes.WinError(ctypes.get_last_error())
    # kernel time includes idle time, matching sysmetrics.cpu_percent's contract.
    return (_ticks(idle), _ticks(kernel), _ticks(user))


class CpuSampler:
    """Stateful busy-CPU% sampler. First sample() returns 0.0 (baseline)."""

    def __init__(self):
        self._prev = None

    def sample(self):
        cur = _read_times()
        if self._prev is None:
            self._prev = cur
            return 0.0
        pct = sysmetrics.cpu_percent(self._prev, cur)
        self._prev = cur
        return pct


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


_kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL
_kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MEMORYSTATUSEX)]


def ram_percent():
    """Percentage of physical RAM in use (0..100)."""
    m = _MEMORYSTATUSEX()
    m.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    if not _kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
        raise ctypes.WinError(ctypes.get_last_error())
    return float(m.dwMemoryLoad)
