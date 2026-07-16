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
_user32.GetWindowRect.restype = wintypes.BOOL
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetDesktopWindow.restype = wintypes.HWND
_user32.GetDesktopWindow.argtypes = []
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

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


def window_below(hwnd):
    """The root window directly beneath `hwnd` at its center point, or 0 if there
    is none, it resolves to the desktop, or it resolves back to `hwnd` itself.

    `hwnd` (e.g. the cat) is a hit-testable top-most overlay, so a plain
    WindowFromPoint at its center returns `hwnd`. Temporarily OR in
    WS_EX_TRANSPARENT so hit-testing passes through it, read what's underneath,
    then restore the original ex-style in a finally (never leave the cat
    click-through). Does not move or hide the window."""
    rect = wintypes.RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return 0
    cx = (rect.left + rect.right) // 2
    cy = (rect.top + rect.bottom) // 2
    style = int(_get(hwnd, GWL_EXSTYLE) or 0)
    had_transparent = bool(style & WS_EX_TRANSPARENT)
    if not had_transparent:
        _set(hwnd, GWL_EXSTYLE, ctypes.c_void_p(style | WS_EX_TRANSPARENT))
    try:
        found = _user32.WindowFromPoint(wintypes.POINT(cx, cy))
        if not found:
            return 0
        root = int(_user32.GetAncestor(found, GA_ROOT) or found)
    finally:
        if not had_transparent:
            cur = int(_get(hwnd, GWL_EXSTYLE) or 0)
            _set(hwnd, GWL_EXSTYLE, ctypes.c_void_p(cur & ~WS_EX_TRANSPARENT))
    if root == int(hwnd) or root == int(_user32.GetDesktopWindow() or 0):
        return 0
    return root


def window_title(hwnd):
    """The window's title text (GetWindowTextW), or '' on failure/empty."""
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    got = _user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value if got else ""


# --- window snapping (zonekit) -------------------------------------------
# Foreground lookup, DWM frame bounds, and positioning for zone snapping.

import os as _os

_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetForegroundWindow.argtypes = []
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetClassNameW.restype = ctypes.c_int
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.IsWindow.restype = wintypes.BOOL
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsZoomed.restype = wintypes.BOOL
_user32.IsZoomed.argtypes = [wintypes.HWND]
_user32.IsIconic.restype = wintypes.BOOL
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.ShowWindow.restype = wintypes.BOOL
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]

_dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
_dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long  # HRESULT
_dwmapi.DwmGetWindowAttribute.argtypes = [
    wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

GWL_STYLE = -16
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
SW_RESTORE = 9
DWMWA_EXTENDED_FRAME_BOUNDS = 9

#: Shell/system window classes that must never be snapped into a zone.
_UNSNAPPABLE_CLASSES = frozenset({
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "#32768", "Windows.UI.Core.CoreWindow", "XamlExplorerHostIslandWindow",
})


def foreground_window():
    """The current foreground window's hwnd as an int; 0 if none."""
    return int(_user32.GetForegroundWindow() or 0)


def is_window(hwnd):
    return bool(hwnd) and bool(_user32.IsWindow(hwnd))


def window_class(hwnd):
    """The window's class name, or '' on failure."""
    buf = ctypes.create_unicode_buffer(256)
    got = _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value if got else ""


def window_rect(hwnd):
    """(l, t, r, b) from GetWindowRect (includes invisible DWM borders), or None."""
    rect = wintypes.RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return (rect.left, rect.top, rect.right, rect.bottom)


def frame_rect(hwnd):
    """The *visible* frame (DWMWA_EXTENDED_FRAME_BOUNDS): what the user sees,
    excluding the invisible resize borders. Falls back to window_rect."""
    rect = wintypes.RECT()
    hr = _dwmapi.DwmGetWindowAttribute(
        hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(rect), ctypes.sizeof(rect))
    if hr != 0:
        return window_rect(hwnd)
    return (rect.left, rect.top, rect.right, rect.bottom)


def is_snappable(hwnd):
    """True for a normal, visible, movable app window that zone snapping may
    reposition: not ours, not a shell/tool window, not minimized, and with a
    caption or sizing frame (excludes menus, tooltips, splash overlays)."""
    if not is_window(hwnd) or not _user32.IsWindowVisible(hwnd):
        return False
    if _user32.IsIconic(hwnd):
        return False
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == _os.getpid():
        return False
    if window_class(hwnd) in _UNSNAPPABLE_CLASSES:
        return False
    exstyle = int(_get(hwnd, GWL_EXSTYLE) or 0)
    if exstyle & WS_EX_TOOLWINDOW:
        return False
    style = int(_get(hwnd, GWL_STYLE) or 0)
    return bool(style & (WS_CAPTION | WS_THICKFRAME))


def move_window(hwnd, left, top, right, bottom):
    """Position a window so its *visible* frame fills (l, t, r, b): restores a
    maximized/minimized window first, then compensates for the invisible DWM
    borders (raw SetWindowPos leaves ~7 px gaps otherwise). Returns False on
    any failure (e.g. an elevated target under UIPI); never raises."""
    try:
        if not is_window(hwnd):
            return False
        if _user32.IsZoomed(hwnd) or _user32.IsIconic(hwnd):
            _user32.ShowWindow(hwnd, SW_RESTORE)
        win = window_rect(hwnd)
        vis = frame_rect(hwnd)
        if win is None or vis is None:
            return False
        # Grow the target outward by each side's invisible inset.
        x = left - (vis[0] - win[0])
        y = top - (vis[1] - win[1])
        w = (right - left) + (vis[0] - win[0]) + (win[2] - vis[2])
        h = (bottom - top) + (vis[1] - win[1]) + (win[3] - vis[3])
        return bool(_user32.SetWindowPos(
            hwnd, None, x, y, w, h, SWP_NOZORDER | SWP_NOACTIVATE))
    except Exception:
        return False
