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


# --- default output-endpoint: enumeration + switching ----------------------
# Extends the WASAPI plumbing above to (a) list active render (output) endpoints
# with friendly names and (b) set the system default via the undocumented
# IPolicyConfig interface -- the same mechanism NirCmd/SoundVolumeView use. All
# COM here must run on one (the main/tk) thread. Switch verified live 2026-07-03.

_DEVICE_STATE_ACTIVE = 0x1
_STGM_READ = 0
_ROLES = (0, 1, 2)          # eConsole, eMultimedia, eCommunications
_VT_LPWSTR = 31

_CLSID_CPolicyConfigClient = _guid("{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}")
_IID_IPolicyConfig = _guid("{F8679F50-850A-41CF-9C72-430F290290C8}")        # SetDefaultEndpoint slot 13
_IID_IPolicyConfigVista = _guid("{568B9108-44BF-40B4-9006-86AFE5B5B832}")   # SetDefaultEndpoint slot 12


class _PROPERTYKEY(C.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wintypes.DWORD)]


class _PROPVARIANT(C.Structure):   # sized for x64 (24 bytes); VT_LPWSTR ptr at offset 8
    _fields_ = [("vt", wintypes.WORD), ("r1", wintypes.WORD), ("r2", wintypes.WORD),
                ("r3", wintypes.WORD), ("data", c_void_p), ("pad", c_void_p)]


_PKEY_Device_FriendlyName = _PROPERTYKEY(
    _guid("{A45C254E-DF1C-4EFD-8020-67D146A850E0}"), 14)

_com_ready = False
_policy_cache = None       # (interface_ptr, set_default_slot)


def _ensure_com():
    global _com_ready
    if not _com_ready:
        _ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
        _com_ready = True


def _device_id(dev):
    pid = c_wchar_p()
    # IMMDevice::GetId == slot 5
    if _method(dev, 5, _HRESULT, POINTER(c_wchar_p))(dev, byref(pid)) < 0:
        return None
    val = pid.value
    try:
        _ole32.CoTaskMemFree(pid)
    except Exception:
        pass
    return val


def _friendly_name(dev):
    store = c_void_p()
    # IMMDevice::OpenPropertyStore == slot 4
    if _method(dev, 4, _HRESULT, wintypes.DWORD, POINTER(c_void_p))(
            dev, _STGM_READ, byref(store)) < 0:
        return None
    pv = _PROPVARIANT()
    # IPropertyStore::GetValue == slot 5
    hr = _method(store, 5, _HRESULT, POINTER(_PROPERTYKEY), POINTER(_PROPVARIANT))(
        store, byref(_PKEY_Device_FriendlyName), byref(pv))
    name = C.cast(pv.data, c_wchar_p).value if hr >= 0 and pv.vt == _VT_LPWSTR else None
    try:
        _ole32.PropVariantClear(byref(pv))
    except Exception:
        pass
    _release(store)
    return name


def list_render_devices():
    """[(endpoint_id, friendly_name), ...] for ACTIVE output devices. [] on error."""
    _ensure_com()
    enum = c_void_p()
    if _ole32.CoCreateInstance(byref(_CLSID_MMDeviceEnumerator), None, _CLSCTX_ALL,
                               byref(_IID_IMMDeviceEnumerator), byref(enum)) < 0:
        return []
    coll = c_void_p()
    # IMMDeviceEnumerator::EnumAudioEndpoints == slot 3
    hr = _method(enum, 3, _HRESULT, C.c_int, wintypes.DWORD, POINTER(c_void_p))(
        enum, _eRender, _DEVICE_STATE_ACTIVE, byref(coll))
    if hr < 0:
        _release(enum)
        return []
    n = C.c_uint()
    # IMMDeviceCollection::GetCount == slot 3
    _method(coll, 3, _HRESULT, POINTER(C.c_uint))(coll, byref(n))
    out = []
    for i in range(n.value):
        d = c_void_p()
        # IMMDeviceCollection::Item == slot 4
        if _method(coll, 4, _HRESULT, C.c_uint, POINTER(c_void_p))(coll, i, byref(d)) < 0:
            continue
        did = _device_id(d)
        name = _friendly_name(d)
        _release(d)
        if did:
            out.append((did, name or ""))
    _release(coll)
    _release(enum)
    return out


def default_render_id():
    """Endpoint id of the current default output device, or None."""
    _ensure_com()
    enum = c_void_p()
    if _ole32.CoCreateInstance(byref(_CLSID_MMDeviceEnumerator), None, _CLSCTX_ALL,
                               byref(_IID_IMMDeviceEnumerator), byref(enum)) < 0:
        return None
    dev = c_void_p()
    # IMMDeviceEnumerator::GetDefaultAudioEndpoint == slot 4
    hr = _method(enum, 4, _HRESULT, C.c_int, C.c_int, POINTER(c_void_p))(
        enum, _eRender, _eConsole, byref(dev))
    did = _device_id(dev) if hr >= 0 else None
    if hr >= 0:
        _release(dev)
    _release(enum)
    return did


def _policy():
    global _policy_cache
    if _policy_cache is not None:
        return _policy_cache
    for iid, slot in ((_IID_IPolicyConfig, 13), (_IID_IPolicyConfigVista, 12)):
        p = c_void_p()
        hr = _ole32.CoCreateInstance(byref(_CLSID_CPolicyConfigClient), None,
                                     _CLSCTX_ALL, byref(iid), byref(p))
        if hr >= 0 and p.value:
            _policy_cache = (p, slot)
            return _policy_cache
    return None


def set_default_render(device_id):
    """Make device_id the default output for all roles. True on success."""
    if not device_id:
        return False
    _ensure_com()
    pol = _policy()
    if not pol:
        return False
    p, slot = pol
    ok = True
    for role in _ROLES:
        # IPolicyConfig::SetDefaultEndpoint(LPCWSTR wszDeviceId, ERole eRole)
        if _method(p, slot, _HRESULT, c_wchar_p, C.c_int)(p, device_id, role) < 0:
            ok = False
    return ok


def match_device(devices, wanted_id, name_substr):
    """Pick an endpoint id from `devices` [(id,name),...]: prefer an exact id
    match; else the first device whose name contains `name_substr`
    (case-insensitive); else None. Empty inputs never match."""
    ids = {d[0] for d in devices}
    if wanted_id and wanted_id in ids:
        return wanted_id
    if name_substr:
        low = name_substr.lower()
        for did, name in devices:
            if name and low in name.lower():
                return did
    return None


def active_slot(current_default_id, speaker_id, headphone_id):
    """Which configured slot ('speaker'/'headphone') the current default matches,
    or None. A blank current default never matches an unconfigured slot."""
    if current_default_id and current_default_id == speaker_id:
        return "speaker"
    if current_default_id and current_default_id == headphone_id:
        return "headphone"
    return None
