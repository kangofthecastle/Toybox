"""Overlay window helpers: DPI awareness and extended-style application.

The caller owns overrideredirect / -topmost / -transparentcolor / -alpha /
geometry on the tk window; this module only flips the native extended styles
(layered, click-through, tool-window, no-activate) that tkinter cannot set,
64-bit-safely. See docs/superpowers/specs/2026-06-24-native-gotchas.md section 1.
"""
import ctypes
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

WS_EX_TOPMOST = 0x00000008
GA_ROOT = 2
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2

#: Sentinel transparent color for shaped pet windows. Never paint with it.
KEY_COLOR = "#010101"

# 64-bit-safe LONG_PTR accessors (fall back to 32-bit names on x86).
_get = getattr(_user32, "GetWindowLongPtrW", None) or _user32.GetWindowLongW
_set = getattr(_user32, "SetWindowLongPtrW", None) or _user32.SetWindowLongW
_get.restype = ctypes.c_void_p
_get.argtypes = [wintypes.HWND, ctypes.c_int]
_set.restype = ctypes.c_void_p
_set.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]

_user32.GetParent.restype = wintypes.HWND
_user32.GetParent.argtypes = [wintypes.HWND]
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
_user32.WindowFromPoint.restype = wintypes.HWND
_user32.WindowFromPoint.argtypes = [wintypes.POINT]
_user32.GetAncestor.restype = wintypes.HWND
_user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.PostMessageW.restype = wintypes.BOOL
_user32.PostMessageW.argtypes = [
    wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

WM_NULL = 0x0000


def enable_dpi_awareness():
    """Make the process DPI-aware. Call ONCE before tk.Tk() so overlay
    coordinates map to physical pixels of the windows beneath."""
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2
        return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _hwnd_of(window):
    wid = window.winfo_id()
    parent = _user32.GetParent(wid)
    return int(parent) if parent else int(wid)


def apply_overlay_styles(window, *, clickthrough=False, tool_window=True, no_activate=False):
    """Apply layered/click-through/tool-window extended styles to a realized
    tk window (call window.update() first). Read-modify-write so tk's own
    styles survive. Returns the hwnd as an int."""
    hwnd = _hwnd_of(window)
    style = int(_get(hwnd, GWL_EXSTYLE) or 0)
    style |= WS_EX_LAYERED
    if tool_window:
        style |= WS_EX_TOOLWINDOW
    if clickthrough:
        style |= WS_EX_TRANSPARENT
        no_activate = True
    if no_activate:
        style |= WS_EX_NOACTIVATE
    _set(hwnd, GWL_EXSTYLE, ctypes.c_void_p(style))
    _user32.SetWindowPos(
        hwnd, None, 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED | SWP_NOACTIVATE,
    )
    return hwnd


def is_topmost(hwnd):
    return bool(int(_get(hwnd, GWL_EXSTYLE) or 0) & WS_EX_TOPMOST)


def set_topmost(hwnd, on):
    """Toggle a window's always-on-top z-order. Returns the SetWindowPos BOOL."""
    insert_after = HWND_TOPMOST if on else HWND_NOTOPMOST
    return bool(_user32.SetWindowPos(
        hwnd, ctypes.c_void_p(insert_after), 0, 0, 0, 0,
        SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE))


def foreground_for_popup(hwnd):
    """Bring a normally no-activate overlay window to the foreground so a native
    popup menu it owns dismisses when the user clicks outside it.

    A WS_EX_NOACTIVATE window never becomes the foreground window, and Windows
    only auto-dismisses a TrackPopupMenu whose owner is the foreground window
    (KB135788). Temporarily clear NOACTIVATE and SetForegroundWindow before the
    menu is posted. Returns a restore() to call once the menu closes: it posts a
    benign WM_NULL (the second half of the KB135788 workaround) and re-applies
    NOACTIVATE so later clicks/drags on the cat don't steal focus again."""
    style = int(_get(hwnd, GWL_EXSTYLE) or 0)
    had_noactivate = bool(style & WS_EX_NOACTIVATE)
    if had_noactivate:
        _set(hwnd, GWL_EXSTYLE, ctypes.c_void_p(style & ~WS_EX_NOACTIVATE))
    _user32.SetForegroundWindow(hwnd)

    def restore():
        _user32.PostMessageW(hwnd, WM_NULL, 0, 0)
        if had_noactivate:
            cur = int(_get(hwnd, GWL_EXSTYLE) or 0)
            _set(hwnd, GWL_EXSTYLE, ctypes.c_void_p(cur | WS_EX_NOACTIVATE))

    return restore


def root_window_at(x, y):
    """The top-level (root ancestor) window under screen point (x, y); 0 if none."""
    pt = wintypes.POINT(x, y)
    hwnd = _user32.WindowFromPoint(pt)
    if not hwnd:
        return 0
    root = _user32.GetAncestor(hwnd, GA_ROOT)
    return int(root or hwnd)
