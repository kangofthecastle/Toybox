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
        self._poll()

    def stop(self):
        self._stopped = True

    def _combo_down(self):
        return all(key_down(vk) for vk in self.vks)

    def _poll(self):
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
                self.root.after(self.interval, self._poll)
