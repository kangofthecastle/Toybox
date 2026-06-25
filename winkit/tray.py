"""System-tray icon with a dynamic right-click popup menu (pure ctypes).

One TrayIcon per process; run() owns this thread's Win32 message loop. The menu
is rebuilt from menu_provider() on each click so it reflects live state. See
gotchas section 6 (keep WNDPROC alive, LRESULT=c_ssize_t, v4, foreground+WM_NULL
around TrackPopupMenu, re-add on TaskbarCreated, NIM_DELETE on teardown).
"""
import ctypes as C
import ctypes.wintypes as w
import os

_u32 = C.WinDLL("user32", use_last_error=True)
_shell = C.WinDLL("shell32", use_last_error=True)
_k32 = C.WinDLL("kernel32", use_last_error=True)

LRESULT = C.c_ssize_t
UINT_PTR = C.c_size_t
WNDPROC = C.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)

WM_DESTROY, WM_CLOSE, WM_COMMAND, WM_NULL, WM_TIMER = 0x0002, 0x0010, 0x0111, 0x0000, 0x0113
WM_LBUTTONUP, WM_RBUTTONUP, WM_CONTEXTMENU = 0x0202, 0x0205, 0x007B
WM_USER = 0x0400
CB_MESSAGE = WM_USER + 1
NIM_ADD, NIM_MODIFY, NIM_DELETE, NIM_SETVERSION = 0, 1, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
IDI_APPLICATION = 32512
IMAGE_ICON = 1
LR_LOADFROMFILE = 0x00000010
LR_DEFAULTSIZE = 0x00000040
MF_STRING, MF_CHECKED, MF_SEPARATOR, MF_GRAYED = 0x0000, 0x0008, 0x0800, 0x0001
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_NONOTIFY = 0x0002, 0x0100, 0x0080
NOTIFYICON_VERSION_4 = 4


class _GUID(C.Structure):
    _fields_ = [("Data1", w.DWORD), ("Data2", w.WORD), ("Data3", w.WORD),
                ("Data4", C.c_ubyte * 8)]


class _POINT(C.Structure):
    _fields_ = [("x", C.c_long), ("y", C.c_long)]


class _MSG(C.Structure):
    _fields_ = [("hwnd", w.HWND), ("message", w.UINT), ("wParam", w.WPARAM),
                ("lParam", w.LPARAM), ("time", w.DWORD), ("pt", _POINT)]


class _NOTIFYICONDATAW(C.Structure):
    _fields_ = [
        ("cbSize", w.DWORD), ("hWnd", w.HWND), ("uID", w.UINT), ("uFlags", w.UINT),
        ("uCallbackMessage", w.UINT), ("hIcon", w.HICON), ("szTip", w.WCHAR * 128),
        ("dwState", w.DWORD), ("dwStateMask", w.DWORD), ("szInfo", w.WCHAR * 256),
        ("uVersion", w.UINT), ("szInfoTitle", w.WCHAR * 64), ("dwInfoFlags", w.DWORD),
        ("guidItem", _GUID), ("hBalloonIcon", w.HICON),
    ]


class _WNDCLASSEX(C.Structure):
    _fields_ = [
        ("cbSize", w.UINT), ("style", w.UINT), ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", C.c_int), ("cbWndExtra", C.c_int), ("hInstance", w.HINSTANCE),
        ("hIcon", w.HICON), ("hCursor", w.HANDLE), ("hbrBackground", w.HBRUSH),
        ("lpszMenuName", w.LPCWSTR), ("lpszClassName", w.LPCWSTR), ("hIconSm", w.HICON),
    ]


_u32.DefWindowProcW.restype = LRESULT
_u32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
_u32.RegisterClassExW.restype = w.ATOM
_u32.RegisterClassExW.argtypes = [C.POINTER(_WNDCLASSEX)]
_u32.CreateWindowExW.restype = w.HWND
_u32.CreateWindowExW.argtypes = [w.DWORD, w.LPCWSTR, w.LPCWSTR, w.DWORD, C.c_int, C.c_int,
                                 C.c_int, C.c_int, w.HWND, w.HMENU, w.HINSTANCE, w.LPVOID]
_u32.DestroyWindow.argtypes = [w.HWND]
_u32.LoadIconW.restype = w.HICON
_u32.LoadIconW.argtypes = [w.HINSTANCE, w.LPCWSTR]
_u32.LoadImageW.restype = w.HANDLE
_u32.LoadImageW.argtypes = [w.HINSTANCE, w.LPCWSTR, w.UINT, C.c_int, C.c_int, w.UINT]
_u32.CreatePopupMenu.restype = w.HMENU
_u32.AppendMenuW.restype = w.BOOL
_u32.AppendMenuW.argtypes = [w.HMENU, w.UINT, UINT_PTR, w.LPCWSTR]
_u32.TrackPopupMenu.restype = C.c_int
_u32.TrackPopupMenu.argtypes = [w.HMENU, w.UINT, C.c_int, C.c_int, C.c_int, w.HWND, w.LPVOID]
_u32.DestroyMenu.argtypes = [w.HMENU]
_u32.GetCursorPos.argtypes = [C.POINTER(_POINT)]
_u32.SetForegroundWindow.argtypes = [w.HWND]
_u32.PostMessageW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]
_u32.RegisterWindowMessageW.restype = w.UINT
_u32.RegisterWindowMessageW.argtypes = [w.LPCWSTR]
_u32.GetMessageW.restype = C.c_int
_u32.GetMessageW.argtypes = [C.POINTER(_MSG), w.HWND, w.UINT, w.UINT]
_u32.TranslateMessage.argtypes = [C.POINTER(_MSG)]
_u32.DispatchMessageW.argtypes = [C.POINTER(_MSG)]
_u32.SetTimer.restype = UINT_PTR
_u32.SetTimer.argtypes = [w.HWND, UINT_PTR, w.UINT, w.LPVOID]
_u32.KillTimer.argtypes = [w.HWND, UINT_PTR]
_shell.Shell_NotifyIconW.restype = w.BOOL
_shell.Shell_NotifyIconW.argtypes = [w.DWORD, C.POINTER(_NOTIFYICONDATAW)]
_k32.GetModuleHandleW.restype = w.HMODULE
_k32.GetModuleHandleW.argtypes = [w.LPCWSTR]

_SMOKE_TIMER_ID = 1


class TrayIcon:
    """tip: tooltip text. menu_provider: () -> list of item dicts, each one of
    {"separator": True} | {"label": str, "callback": callable, "checked": bool}."""

    def __init__(self, tip, menu_provider, class_name="ToyboxTrayWnd", icon_path=None):
        self.menu_provider = menu_provider
        self._cmds = {}
        self._destroyed = False
        self._wndproc = WNDPROC(self._wnd_proc)  # KEEP a strong ref or GC -> crash
        self._taskbar_created = _u32.RegisterWindowMessageW("TaskbarCreated")
        hinst = _k32.GetModuleHandleW(None)

        self._wc = _WNDCLASSEX()
        self._wc.cbSize = C.sizeof(_WNDCLASSEX)
        self._wc.lpfnWndProc = self._wndproc
        self._wc.hInstance = hinst
        self._wc.lpszClassName = class_name
        _u32.RegisterClassExW(C.byref(self._wc))  # ERROR_CLASS_ALREADY_EXISTS is fine

        self.hwnd = _u32.CreateWindowExW(0, class_name, "Toybox", 0, 0, 0, 0, 0,
                                         None, None, hinst, None)  # no ShowWindow -> invisible
        if not self.hwnd:
            raise C.WinError(C.get_last_error())

        self._hicon = 0
        if icon_path and os.path.exists(icon_path):
            self._hicon = _u32.LoadImageW(None, icon_path, IMAGE_ICON, 0, 0,
                                          LR_LOADFROMFILE | LR_DEFAULTSIZE)
        if not self._hicon:  # fall back to the stock application icon
            self._hicon = _u32.LoadIconW(None, C.cast(C.c_void_p(IDI_APPLICATION), w.LPCWSTR))
        self._nid = _NOTIFYICONDATAW()
        self._nid.cbSize = C.sizeof(_NOTIFYICONDATAW)
        self._nid.hWnd = self.hwnd
        self._nid.uID = 1
        self._nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        self._nid.uCallbackMessage = CB_MESSAGE
        self._nid.hIcon = self._hicon
        self._nid.szTip = tip
        self._add_icon()

        smoke = os.environ.get("TOYBOX_SMOKE")
        if smoke:
            _u32.SetTimer(self.hwnd, _SMOKE_TIMER_ID, int(smoke), None)

    def _add_icon(self):
        _shell.Shell_NotifyIconW(NIM_ADD, C.byref(self._nid))
        self._nid.uVersion = NOTIFYICON_VERSION_4
        _shell.Shell_NotifyIconW(NIM_SETVERSION, C.byref(self._nid))

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == self._taskbar_created:
            self._add_icon()
            return 0
        if msg == CB_MESSAGE:
            if (lparam & 0xFFFF) in (WM_RBUTTONUP, WM_LBUTTONUP, WM_CONTEXTMENU):
                self._show_menu()
            return 0
        if msg == WM_TIMER and wparam == _SMOKE_TIMER_ID:
            _u32.KillTimer(self.hwnd, _SMOKE_TIMER_ID)
            self._destroy()
            return 0
        if msg == WM_CLOSE:
            self._destroy()
            return 0
        if msg == WM_DESTROY:
            _u32.PostQuitMessage(0)
            return 0
        return _u32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _show_menu(self):
        try:
            items = self.menu_provider() or []
        except Exception:
            items = []
        hmenu = _u32.CreatePopupMenu()
        self._cmds = {}
        next_id = 1
        for item in items:
            if item.get("separator"):
                _u32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
                continue
            flags = MF_STRING
            if item.get("checked"):
                flags |= MF_CHECKED
            if item.get("disabled"):
                flags |= MF_GRAYED
            _u32.AppendMenuW(hmenu, flags, next_id, item["label"])
            self._cmds[next_id] = item.get("callback")
            next_id += 1
        pt = _POINT()
        _u32.GetCursorPos(C.byref(pt))
        _u32.SetForegroundWindow(self.hwnd)  # required before TrackPopupMenu
        cmd = _u32.TrackPopupMenu(hmenu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
                                  pt.x, pt.y, 0, self.hwnd, None)
        _u32.PostMessageW(self.hwnd, WM_NULL, 0, 0)  # required after
        _u32.DestroyMenu(hmenu)
        if cmd:
            cb = self._cmds.get(int(cmd))
            if cb:
                try:
                    cb()
                except Exception:
                    pass

    def request_quit(self):
        """Ask the loop to exit (safe to call from a timer/another thread)."""
        _u32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def _destroy(self):
        if self._destroyed:
            return
        self._destroyed = True
        _shell.Shell_NotifyIconW(NIM_DELETE, C.byref(self._nid))  # else ghost icon lingers
        _u32.DestroyWindow(self.hwnd)

    def run(self):
        msg = _MSG()
        try:
            while _u32.GetMessageW(C.byref(msg), None, 0, 0) > 0:
                _u32.TranslateMessage(C.byref(msg))
                _u32.DispatchMessageW(C.byref(msg))
        finally:
            self.close()

    def close(self):
        self._destroy()
