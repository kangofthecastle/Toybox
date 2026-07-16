r"""Display-settings control: read and rotate a monitor's orientation.

Rotating a physical display means reading the monitor's current mode with
EnumDisplaySettingsW, bumping dmDisplayOrientation (DMDO_DEFAULT/90/180/270),
swapping dmPelsWidth/dmPelsHeight whenever the turn crosses the
landscape<->portrait boundary, then applying it with ChangeDisplaySettingsExW
(tested first, then persisted to the registry).

Device names are the \\.\DISPLAY1 form returned by winkit.monitors. All
ctypes signatures are explicit (argtypes/restype) and the DEVMODEW layout is
spelled out in full -- the two anonymous unions are represented by their display
branch and their first member respectively -- per the 64-bit rules in
docs/superpowers/specs/2026-06-24-native-gotchas.md. Nothing here raises: callers
get a bool / small int / None back.
"""
import ctypes
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)

# dmDisplayOrientation values; each step is one 90-degree clockwise quarter-turn.
DMDO_DEFAULT = 0   # landscape
DMDO_90 = 1        # portrait
DMDO_180 = 2       # landscape (flipped)
DMDO_270 = 3       # portrait (flipped)

# dmFields bits for the members we set.
DM_DISPLAYORIENTATION = 0x00000080
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000

ENUM_CURRENT_SETTINGS = 0xFFFFFFFF   # (DWORD)-1
CDS_UPDATEREGISTRY = 0x00000001
CDS_TEST = 0x00000002
DISP_CHANGE_SUCCESSFUL = 0


class _POINTL(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _DEVMODE_DISPLAY(ctypes.Structure):
    # The display branch of DEVMODEW's first anonymous union: 16 bytes, matching
    # the printer branch's eight shorts, so every field after it keeps its offset.
    _fields_ = [
        ("dmPosition", _POINTL),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
    ]


class _DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmDisplay", _DEVMODE_DISPLAY),        # first union (display branch)
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),     # second union's first member (dmNup)
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


_user32.EnumDisplaySettingsW.restype = wintypes.BOOL
_user32.EnumDisplaySettingsW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(_DEVMODEW)]
_user32.ChangeDisplaySettingsExW.restype = wintypes.LONG
_user32.ChangeDisplaySettingsExW.argtypes = [
    wintypes.LPCWSTR, ctypes.POINTER(_DEVMODEW), wintypes.HWND,
    wintypes.DWORD, wintypes.LPVOID]


# --- pure orientation math (unit-tested; no ctypes needed) ----------------
def next_orientation(current, steps=1):
    """The DMDO_* orientation `steps` quarter-turns clockwise from `current`,
    wrapping 0->1->2->3->0."""
    return (int(current) + int(steps)) & 3


def needs_dimension_swap(current, target):
    """True when rotating current->target crosses the landscape<->portrait
    boundary (an odd number of quarter-turns), so width/height must be swapped."""
    return bool((int(current) ^ int(target)) & 1)


# --- native read/apply ----------------------------------------------------
def _current_devmode(device):
    dm = _DEVMODEW()
    dm.dmSize = ctypes.sizeof(_DEVMODEW)
    if not _user32.EnumDisplaySettingsW(device, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)):
        return None
    return dm


def orientation(device):
    """The monitor's current orientation (a DMDO_* value), or None if the device
    can't be queried."""
    dm = _current_devmode(device)
    return None if dm is None else int(dm.dmDisplay.dmDisplayOrientation)


def set_orientation(device, target):
    r"""Rotate `device` (a \\.\DISPLAYn name) to absolute orientation `target`
    (0..3), swapping width/height across the landscape<->portrait boundary. The
    mode is validated with CDS_TEST before being applied+persisted with
    CDS_UPDATEREGISTRY. Returns True only on DISP_CHANGE_SUCCESSFUL."""
    dm = _current_devmode(device)
    if dm is None:
        return False
    target &= 3
    if needs_dimension_swap(dm.dmDisplay.dmDisplayOrientation, target):
        dm.dmPelsWidth, dm.dmPelsHeight = dm.dmPelsHeight, dm.dmPelsWidth
    dm.dmDisplay.dmDisplayOrientation = target
    dm.dmFields = DM_DISPLAYORIENTATION | DM_PELSWIDTH | DM_PELSHEIGHT
    if _user32.ChangeDisplaySettingsExW(
            device, ctypes.byref(dm), None, CDS_TEST, None) != DISP_CHANGE_SUCCESSFUL:
        return False
    return _user32.ChangeDisplaySettingsExW(
        device, ctypes.byref(dm), None, CDS_UPDATEREGISTRY, None) == DISP_CHANGE_SUCCESSFUL


def cycle_orientation(device, steps=1):
    """Rotate `device` a further `steps` quarter-turns clockwise from its current
    orientation (0->90->180->270->0). Returns (ok, new_orientation) where
    new_orientation is the DMDO_* value that was requested, or (False, None) if
    the device is unreadable."""
    cur = orientation(device)
    if cur is None:
        return (False, None)
    target = next_orientation(cur, steps)
    return (set_orientation(device, target), target)
