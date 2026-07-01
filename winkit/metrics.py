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


# --- GPU utilization via PDH GPU Engine counters --------------------------
_pdh = ctypes.WinDLL("pdh", use_last_error=True)

PDH_FMT_DOUBLE = 0x00000200
PDH_MORE_DATA = 0x800007D2
_GPU_COUNTER_PATH = r"\GPU Engine(*)\Utilization Percentage"
_PDH_VALID_CSTATUS = (0x00000000, 0x00000001)  # VALID_DATA, NEW_DATA


class _PDH_FMT_COUNTERVALUE(ctypes.Structure):
    # DWORD CStatus; then an 8-byte union -> ctypes pads to align the double at 8.
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


class _PDH_FMT_COUNTERVALUE_ITEM_W(ctypes.Structure):
    _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", _PDH_FMT_COUNTERVALUE)]


_pdh.PdhOpenQueryW.restype = wintypes.DWORD
_pdh.PdhOpenQueryW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p,
                               ctypes.POINTER(ctypes.c_void_p)]
_pdh.PdhAddEnglishCounterW.restype = wintypes.DWORD
_pdh.PdhAddEnglishCounterW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                       ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
_pdh.PdhCollectQueryData.restype = wintypes.DWORD
_pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
_pdh.PdhGetFormattedCounterArrayW.restype = wintypes.DWORD
_pdh.PdhGetFormattedCounterArrayW.argtypes = [
    ctypes.c_void_p, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]


class GpuSampler:
    """Stateful GPU-utilization sampler over the PDH GPU Engine counters.

    sample() returns a 0..100 float, or None when GPU counters are unavailable
    (the HUD then shows 'GPU --%'). Never raises. Mirrors CpuSampler: __init__
    opens the query and takes a baseline collect, so the first sample() may read
    low until two collections span an interval."""

    def __init__(self):
        self._query = None
        self._counter = None
        try:
            hq = ctypes.c_void_p()
            if _pdh.PdhOpenQueryW(None, 0, ctypes.byref(hq)) != 0:
                return
            hc = ctypes.c_void_p()
            if _pdh.PdhAddEnglishCounterW(hq, _GPU_COUNTER_PATH, 0, ctypes.byref(hc)) != 0:
                return
            _pdh.PdhCollectQueryData(hq)   # baseline for the rate counter
            self._query = hq
            self._counter = hc
        except Exception:
            self._query = None
            self._counter = None

    def sample(self):
        if self._query is None or self._counter is None:
            return None
        try:
            if _pdh.PdhCollectQueryData(self._query) != 0:
                return None
            size = wintypes.DWORD(0)
            count = wintypes.DWORD(0)
            status = _pdh.PdhGetFormattedCounterArrayW(
                self._counter, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count), None)
            if status != PDH_MORE_DATA or size.value == 0:
                return None
            buf = (ctypes.c_byte * size.value)()
            status = _pdh.PdhGetFormattedCounterArrayW(
                self._counter, PDH_FMT_DOUBLE, ctypes.byref(size), ctypes.byref(count),
                ctypes.cast(buf, ctypes.c_void_p))
            if status != 0:
                return None
            items = ctypes.cast(buf, ctypes.POINTER(_PDH_FMT_COUNTERVALUE_ITEM_W))
            pairs = []
            for i in range(count.value):
                it = items[i]
                if it.FmtValue.CStatus in _PDH_VALID_CSTATUS and it.szName:
                    pairs.append((it.szName, it.FmtValue.doubleValue))
            return sysmetrics.gpu_percent(pairs)
        except Exception:
            return None
