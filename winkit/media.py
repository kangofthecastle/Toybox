"""System media controls: play/pause, next, and previous track via the media
virtual-keys (WM_APPCOMMAND equivalents). Player-agnostic; no now-playing state
is read. Pure ctypes on user32 -- no pip."""
import ctypes
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD,
                                ctypes.c_void_p]
_user32.keybd_event.restype = None

VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3
KEYEVENTF_KEYUP = 0x0002


def _keybd_event(vk, flags):
    """Single ctypes call (the test seam). Swallows failures -- a media key no
    app consumes is a harmless no-op, never a crash."""
    try:
        _user32.keybd_event(vk, 0, flags, 0)
    except Exception:
        pass


def _tap(vk):
    _keybd_event(vk, 0)
    _keybd_event(vk, KEYEVENTF_KEYUP)


def play_pause():
    _tap(VK_MEDIA_PLAY_PAUSE)


def next_track():
    _tap(VK_MEDIA_NEXT_TRACK)


def prev_track():
    _tap(VK_MEDIA_PREV_TRACK)
