"""Catch & Carry native glue: build a CF_HDROP blob and put dropped file paths
on the clipboard, plus a WM_DROPFILES wndproc subclass (FileDropTarget, Task 4).

The byte-layout builder is pure and unit-tested; the Win32 calls follow the
64-bit-safe idiom in winkit/tray.py."""
import ctypes
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
