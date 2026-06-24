"""System audio output peak meter via WASAPI IAudioMeterInformation (pure ctypes COM).

Reads the post-mix, all-apps-combined instantaneous peak (0..1) on the default
render endpoint. Self-healing: any failed HRESULT (e.g. device switched,
AUDCLNT_E_DEVICE_INVALIDATED) rebuilds the endpoint. Construct and read on the
same (main/tk) thread. See gotchas section 2; validated by spike 2026-06-24.
"""
import ctypes as C
from ctypes import wintypes, POINTER, byref, c_float, c_void_p, c_ulong, c_wchar_p

_ole32 = C.windll.ole32
_HRESULT = C.c_long
_COINIT_APARTMENTTHREADED = 0x2
_CLSCTX_ALL = 0x17
_eRender, _eConsole = 0, 0
_RPC_E_CHANGED_MODE = 0x80010106

_ole32.CoInitializeEx.restype = C.c_long
_ole32.CoInitializeEx.argtypes = [C.c_void_p, wintypes.DWORD]


class _GUID(C.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", C.c_ubyte * 8)]


def _guid(s):
    g = _GUID()
    _ole32.CLSIDFromString(c_wchar_p(s), byref(g))
    return g


_CLSID_MMDeviceEnumerator = _guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
_IID_IMMDeviceEnumerator = _guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
_IID_IAudioMeterInformation = _guid("{C02216F6-8C67-4B5B-9D00-D008E73E0064}")


def _vtbl(p):
    return C.cast(p, POINTER(POINTER(c_void_p)))[0]


def _method(p, idx, restype, *argtypes):
    return C.WINFUNCTYPE(restype, c_void_p, *argtypes)(_vtbl(p)[idx])


def _release(p):
    if p:
        _method(p, 2, c_ulong)(p)  # IUnknown::Release is vtable slot 2


def _build_meter():
    enum = c_void_p()
    if _ole32.CoCreateInstance(byref(_CLSID_MMDeviceEnumerator), None, _CLSCTX_ALL,
                               byref(_IID_IMMDeviceEnumerator), byref(enum)) < 0:
        return None, None
    dev = c_void_p()
    # IMMDeviceEnumerator::GetDefaultAudioEndpoint == slot 4
    hr = _method(enum, 4, _HRESULT, C.c_int, C.c_int, POINTER(c_void_p))(
        enum, _eRender, _eConsole, byref(dev))
    _release(enum)
    if hr < 0:
        return None, None
    meter = c_void_p()
    # IMMDevice::Activate == slot 3
    hr = _method(dev, 3, _HRESULT, POINTER(_GUID), wintypes.DWORD, c_void_p, POINTER(c_void_p))(
        dev, byref(_IID_IAudioMeterInformation), _CLSCTX_ALL, None, byref(meter))
    if hr < 0:
        _release(dev)
        return None, None
    return dev, meter


class AudioPeakMeter:
    def __init__(self, rebuild_every=64):
        # Only balance with CoUninitialize if WE initialized COM. S_OK (0) and
        # S_FALSE (1) mean we did; RPC_E_CHANGED_MODE means someone else already
        # owns the apartment (we must NOT uninitialize their count).
        hr = _ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED) & 0xFFFFFFFF
        self._co_owned = hr in (0, 1)
        self.dev = None
        self.meter = None
        self._rebuild_every = rebuild_every
        self._count = 0
        self._rebuild()

    def _rebuild(self):
        _release(self.meter)
        _release(self.dev)
        self.dev, self.meter = _build_meter()

    def read(self):
        """Return the current output peak 0.0..1.0 (0.0 on silence or any error)."""
        self._count += 1
        if self._rebuild_every and self._count % self._rebuild_every == 0:
            self._rebuild()  # follow silent default-device switches
        if not self.meter:
            self._rebuild()
            if not self.meter:
                return 0.0
        peak = c_float()
        # IAudioMeterInformation::GetPeakValue == slot 3
        hr = _method(self.meter, 3, _HRESULT, POINTER(c_float))(self.meter, byref(peak))
        if hr < 0:
            self._rebuild()
            return 0.0
        return peak.value

    def close(self):
        _release(self.meter)
        _release(self.dev)
        self.meter = self.dev = None
        if self._co_owned:
            try:
                _ole32.CoUninitialize()
            except Exception:
                pass
            self._co_owned = False
