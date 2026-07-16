"""Keyboard/clipboard polling: clipboard change detection and edge-detected hotkeys.

Uses GetAsyncKeyState's high bit only (the low bit is unreliable) and does
edge detection in Python so a held chord fires once. See gotchas section 3.
"""
import ctypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetAsyncKeyState.restype = ctypes.c_short
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetClipboardSequenceNumber.restype = ctypes.c_uint
_user32.GetClipboardSequenceNumber.argtypes = []

# Generic (either-side) modifier virtual-key codes.
_MODS = {
    "ctrl": 0x11, "control": 0x11,
    "shift": 0x10,
    "alt": 0x12, "menu": 0x12,
    "win": 0x5B,
}


def vk_for(token):
    """Map a token to a virtual-key code. 'ctrl'/'shift'/'alt'/'win' or a single
    character (letters/digits use uppercase ASCII). Raises ValueError otherwise."""
    t = token.lower()
    if t in _MODS:
        return _MODS[t]
    if len(token) == 1:
        return ord(token.upper())
    raise ValueError(f"unknown key token: {token!r}")


def key_down(vk):
    """True if the key is currently down (high bit of GetAsyncKeyState)."""
    return bool(_user32.GetAsyncKeyState(vk) & 0x8000)


_user32.GetSystemMetrics.restype = ctypes.c_int
_user32.GetSystemMetrics.argtypes = [ctypes.c_int]

SM_SWAPBUTTON = 23
VK_LBUTTON, VK_RBUTTON = 0x01, 0x02


def primary_button_vk():
    """VK of the primary ('drag') mouse button. GetAsyncKeyState reports
    PHYSICAL buttons, so a swapped (left-handed) mouse drags with the physical
    right button; read SM_SWAPBUTTON each call so a live swap is honored."""
    return VK_RBUTTON if _user32.GetSystemMetrics(SM_SWAPBUTTON) else VK_LBUTTON


def clipboard_sequence():
    """Monotonic clipboard sequence number; changes whenever the clipboard is written."""
    return int(_user32.GetClipboardSequenceNumber())


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


_user32.GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]
_user32.GetCursorPos.restype = ctypes.c_int  # BOOL


def cursor_pos():
    """Global mouse cursor position in screen pixels, as an (x, y) tuple."""
    pt = _POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return (pt.x, pt.y)


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.GetTickCount.restype = ctypes.c_uint
_kernel32.GetTickCount.argtypes = []


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


_user32.GetLastInputInfo.restype = ctypes.c_int  # BOOL
_user32.GetLastInputInfo.argtypes = [ctypes.POINTER(_LASTINPUTINFO)]


def _idle_ms_from_ticks(last_tick, now_tick):
    """Milliseconds between two GetTickCount samples, 32-bit-wraparound-safe."""
    return (now_tick - last_tick) & 0xFFFFFFFF


def idle_ms():
    """Milliseconds since the last system-wide keyboard/mouse input."""
    info = _LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(_LASTINPUTINFO)
    _user32.GetLastInputInfo(ctypes.byref(info))
    return _idle_ms_from_ticks(info.dwTime, _kernel32.GetTickCount())


class HotkeyPoller:
    """Edge-detected hotkey-combo poller driven by tkinter's after() loop.

    Fires `callback` once on the rising edge of all `tokens` being held; re-arms
    only after the chord is released. A callback exception never kills the loop.
    """

    def __init__(self, root, tokens, callback, interval_ms=66):
        self.root = root
        self.vks = [vk_for(t) for t in tokens]
        self.callback = callback
        self.interval = interval_ms
        self._was_down = False
        self._stopped = False
        self._after_id = None
        self._poll()

    def stop(self):
        self._stopped = True
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)  # no orphaned post-destroy poll
            except Exception:
                pass
            self._after_id = None

    def _combo_down(self):
        return all(key_down(vk) for vk in self.vks)

    def _poll(self):
        self._after_id = None
        if self._stopped:
            return
        try:
            now = self._combo_down()
            if now and not self._was_down:
                self._was_down = True
                try:
                    self.callback()
                except Exception:
                    pass
            elif not now:
                self._was_down = False
        finally:
            if not self._stopped:
                self._after_id = self.root.after(self.interval, self._poll)
