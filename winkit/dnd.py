"""Catch & Carry native glue: build a CF_HDROP blob and put dropped file paths
on the clipboard, plus a WM_DROPFILES wndproc subclass (FileDropTarget, Task 4).

The byte-layout builder is pure and unit-tested; the Win32 calls follow the
64-bit-safe idiom in winkit/tray.py."""
import ctypes
import os
import struct
from ctypes import wintypes

_DROPFILES_SIZE = 20          # sizeof(DROPFILES): pFiles + POINT + fNC + fWide
CF_HDROP = 15
_GMEM_MOVEABLE = 0x0002


def build_dropfiles(paths):
    """A DROPFILES struct followed by a wide, double-NUL-terminated path list."""
    header = struct.pack("<Iiiii", _DROPFILES_SIZE, 0, 0, 0, 1)  # fWide=1
    body = ("".join(p + "\0" for p in paths) + "\0").encode("utf-16-le")
    return header + body


_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
_kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
_user32.OpenClipboard.argtypes = [wintypes.HWND]
_user32.SetClipboardData.restype = wintypes.HANDLE
_user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]


def set_clipboard_files(paths):
    """Put paths on the clipboard as CF_HDROP. Returns True on success."""
    if not paths:
        return False
    blob = build_dropfiles(paths)
    h = _kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(blob))
    if not h:
        return False
    ptr = _kernel32.GlobalLock(h)
    if not ptr:
        _kernel32.GlobalFree(h)
        return False
    ctypes.memmove(ptr, blob, len(blob))
    _kernel32.GlobalUnlock(h)
    if not _user32.OpenClipboard(None):
        _kernel32.GlobalFree(h)
        return False
    try:
        _user32.EmptyClipboard()
        if not _user32.SetClipboardData(CF_HDROP, h):
            _kernel32.GlobalFree(h)     # we still own it on failure
            return False
        return True                      # ownership transferred to the clipboard
    finally:
        _user32.CloseClipboard()


_shell32 = ctypes.WinDLL("shell32", use_last_error=True)
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT,
                             wintypes.WPARAM, wintypes.LPARAM)
GWLP_WNDPROC = -4
WM_DROPFILES = 0x0233

_setlp = getattr(_user32, "SetWindowLongPtrW", None) or _user32.SetWindowLongW
_setlp.restype = ctypes.c_void_p
_setlp.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
_user32.CallWindowProcW.restype = LRESULT
_user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT,
                                    wintypes.WPARAM, wintypes.LPARAM]
_shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
_shell32.DragQueryFileW.restype = wintypes.UINT
_shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT,
                                    wintypes.LPWSTR, wintypes.UINT]
_shell32.DragFinish.argtypes = [wintypes.HANDLE]


def _query_dropped(hdrop):
    count = _shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0)
    paths = []
    for i in range(count):
        need = _shell32.DragQueryFileW(hdrop, i, None, 0)
        buf = ctypes.create_unicode_buffer(need + 1)
        _shell32.DragQueryFileW(hdrop, i, buf, need + 1)
        paths.append(buf.value)
    return paths


class FileDropTarget:
    """Accept WM_DROPFILES on an existing HWND by subclassing its wndproc."""

    def __init__(self, hwnd, on_drop):
        self.hwnd = hwnd
        self.on_drop = on_drop
        self._proc = WNDPROC(self._wnd_proc)        # KEEP a strong ref or GC -> crash
        _shell32.DragAcceptFiles(hwnd, True)
        self._old_proc = _setlp(hwnd, GWLP_WNDPROC,
                                ctypes.cast(self._proc, ctypes.c_void_p)) or 0

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_DROPFILES:
            try:
                paths = _query_dropped(wparam)
                _shell32.DragFinish(wparam)
                if paths:
                    self.on_drop(paths)
            except Exception:
                pass
            return 0
        return _user32.CallWindowProcW(self._old_proc, hwnd, msg, wparam, lparam)

    def close(self):
        if self._old_proc:
            _setlp(self.hwnd, GWLP_WNDPROC, ctypes.c_void_p(self._old_proc))
            self._old_proc = 0
        try:
            _shell32.DragAcceptFiles(self.hwnd, False)
        except Exception:
            pass
