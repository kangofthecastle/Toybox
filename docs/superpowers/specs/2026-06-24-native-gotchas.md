# Native-Code Gotchas & Patterns: Pure-Python-Stdlib Windows Desktop Toys

> Reference for tkinter + ctypes + winreg on Windows 10, Python 3.12. All examples are pure stdlib.

## Highest-Risk Items (read first)

The failures most likely to crash silently or corrupt state:

1. **Garbage-collected `WNDPROC` callback (tray icon)** — ctypes does not hold a reference to your `WINFUNCTYPE` wrapper. If only a local variable holds it, it is freed and the process **hard-crashes** the first time Windows dispatches a message. Store it on a long-lived object.
2. **64-bit handle/`LONG_PTR` truncation across all ctypes Win32 calls** — the default ctypes restype is `c_int` (32-bit). HWNDs, exstyles, `WPARAM`/`LPARAM`/`LRESULT` are pointer-sized (8 bytes) on Win64. Truncation produces `ERROR_INVALID_WINDOW_HANDLE`, styles that don't stick, or AccessViolations — **with no Python exception**. Always set `.argtypes`/`.restype`, use the `*Ptr` window-long variants, and `LRESULT = c_ssize_t`.
3. **COM apartment / thread affinity** — keep ALL COM on the tkinter main thread in an STA (`CoInitializeEx(None, COINIT_APARTMENTTHREADED)` once). Calling an interface from a different thread than created it yields `RPC_E_WRONG_THREAD` or hangs. ctypes does **not** auto-Release; every interface leaks unless you call `Release` (vtable slot 2) explicitly, and `CoUninitialize` must balance `CoInitializeEx` after all interfaces are freed.
4. **`pythonw.exe` startup has `sys.stdout/stderr/stdin == None`** — the #1 cause of "works on double-click, silently dies at login." Any `print`/`traceback`/`logging` StreamHandler raises `AttributeError` and kills the process invisibly. Guard the streams before anything else runs.
5. **GetAsyncKeyState low bit (`0x0001`) is unreliable** — Microsoft says so explicitly; it races across processes. Use only the high bit (`& 0x8000`) and do edge detection yourself.
6. **Wrong vtable slot index in pure-ctypes COM** — silently calls the wrong function and corrupts the stack. Hardcode IUnknown as QI=0/AddRef=1/Release=2; derived methods start at index 3.

---

## 1. Transparent / Click-Through tkinter Window

The crux is the MSDN layered-window hit-test rule: *color-keyed or zero-alpha pixels pass mouse messages through automatically*; adding `WS_EX_TRANSPARENT` makes the **entire** window click-through regardless of pixel. So there are two regimes — pick one.

### Do this

```python
import ctypes, tkinter as tk
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
GWL_EXSTYLE = -20
WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x00080000, 0x00000020
WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x00000080, 0x08000000
SWP = 0x0002 | 0x0001 | 0x0004 | 0x0020 | 0x0010  # NOMOVE|NOSIZE|NOZORDER|FRAMECHANGED|NOACTIVATE

# 64-bit-safe LONG_PTR accessors (fall back to 32-bit names on x86)
_get = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
_set = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
_get.restype = _set.restype = ctypes.c_void_p
_get.argtypes = [wintypes.HWND, ctypes.c_int]
_set.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]

KEY = "#010101"  # sentinel color you never paint with

# DPI awareness BEFORE Tk() so overlay coords == physical pixels of windows beneath
try: ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)      # per-monitor v2
except Exception:
    try: ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception: ctypes.windll.user32.SetProcessDPIAware()

root = tk.Tk()
root.withdraw()                       # set up hidden -> no decorated flash / no taskbar button
root.overrideredirect(True)
root.config(bg=KEY)
root.geometry("800x600+100+100")
root.attributes("-topmost", True)
root.attributes("-transparentcolor", KEY)   # ONE strategy: shaped cutout (LWA_COLORKEY)
# root.attributes("-alpha", 0.6)             # OR uniform translucency -- don't rely on both
tk.Label(root, text="HUD", bg="#202020", fg="white").pack(padx=20, pady=20)

root.update()                         # REALIZE the HWND before touching ex-styles
hwnd = user32.GetParent(root.winfo_id()) or root.winfo_id()

FULL_CLICKTHROUGH = True
def apply_exstyles(hwnd, full):
    s = (_get(hwnd, GWL_EXSTYLE) or 0) | WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
    s = (s | WS_EX_TRANSPARENT) if full else (s & ~WS_EX_TRANSPARENT)  # read-modify-write
    _set(hwnd, GWL_EXSTYLE, s)
    user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP)  # commit frame change + redraw, no activate

apply_exstyles(hwnd, FULL_CLICKTHROUGH)
root.deiconify()                      # reshow AFTER styles -> taskbar button never created
root.mainloop()
```

- **Shaped + interactive overlay** (clicks pass through transparent pixels only; widgets stay clickable): `WS_EX_LAYERED` + color key, and do **not** set `WS_EX_TRANSPARENT`.
- **True ghost overlay** (every pixel passes clicks through): add `WS_EX_TRANSPARENT`.

### Watch out for

- `WS_EX_TRANSPARENT` controls **hit-testing only** — it does not make the window visually transparent. Visible transparency comes from `WS_EX_LAYERED` + `SetLayeredWindowAttributes` (which is what `-alpha` / `-transparentcolor` call under the hood). Always pair the two.
- You **cannot** have an opaque-and-interactive region while `WS_EX_TRANSPARENT` is set — it's all-or-nothing.
- Don't stack `-alpha` and `-transparentcolor` on one toplevel; both map to the single `SetLayeredWindowAttributes` call and `LWA_COLORKEY` + `LWA_ALPHA` is unreliable. Pick one; if you truly need both, drive `SetLayeredWindowAttributes` yourself and test on the target machine.
- The color key is a hard on/off — every pixel of that exact RGB vanishes and becomes a hit-test hole. Never draw real content in the key color; antialiased edges blending toward it will fringe.
- **Read-modify-write** `GWL_EXSTYLE` (OR-in / AND-out). Overwriting (`style = WS_EX_LAYERED | WS_EX_TRANSPARENT`) drops styles Tk already set (topmost/toolwindow).
- Apply ex-styles only **after** `root.update()` realizes the HWND; Tk re-applies its own ex-styles on `-topmost`/remap and can clobber yours — re-apply if you toggle them. Always finish with `SetWindowPos(..., SWP_FRAMECHANGED | SWP_NOACTIVATE)`.
- Use the `*Ptr` long accessors with explicit `c_void_p` types; cast `winfo_id()` via `GetParent` to reach the true top-level frame.
- `WS_EX_NOACTIVATE` stops focus-stealing for interactive overlays; `WS_EX_TOOLWINDOW` removes the taskbar/Alt+Tab entry — but if the button already exists you must `withdraw()` → set style → `deiconify()`. Never add `WS_EX_APPWINDOW`.
- Set DPI awareness **before** `Tk()`, or overlay geometry is in scaled coords and misaligns on >100% displays (and is blurry).
- `-alpha 0` makes the whole window invisible **and** click-through (zero-alpha rule) — keep `bAlpha >= 1` for visible interactive overlays.

---

## 2. WASAPI Peak Meter via ctypes (`IAudioMeterInformation::GetPeakValue`)

### Do this

Self-healing, single-thread (tkinter main thread, STA), pure-ctypes meter. Vtable slots: `IMMDeviceEnumerator.GetDefaultAudioEndpoint=4`, `IMMDevice.Activate=3`, `IAudioMeterInformation.GetPeakValue=3`.

```python
import ctypes as C
from ctypes import wintypes, POINTER, byref, c_float, c_void_p, c_ulong, c_wchar_p

ole32 = C.windll.ole32
HRESULT = C.c_long
COINIT_APARTMENTTHREADED = 0x2
CLSCTX_ALL = 0x17
eRender, eConsole = 0, 0

class GUID(C.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD), ("Data4", C.c_ubyte * 8)]
def guid(s):
    g = GUID(); ole32.CLSIDFromString(c_wchar_p(s), byref(g)); return g  # never hand-pack GUID bytes

CLSID_MMDeviceEnumerator   = guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_IMMDeviceEnumerator    = guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
IID_IAudioMeterInformation = guid("{C02216F6-8C67-4B5B-9D00-D008E73E0064}")

def vtbl(p):    return C.cast(p, POINTER(POINTER(c_void_p)))[0]
def method(p, idx, restype, *argtypes):
    return C.WINFUNCTYPE(restype, c_void_p, *argtypes)(vtbl(p)[idx])  # WINFUNCTYPE = stdcall
def release(p):
    if p: method(p, 2, c_ulong)(p)   # IUnknown::Release == slot 2

def build_meter():
    enum = c_void_p()
    if ole32.CoCreateInstance(byref(CLSID_MMDeviceEnumerator), None, CLSCTX_ALL,
                              byref(IID_IMMDeviceEnumerator), byref(enum)) < 0:
        return None, None
    dev = c_void_p()
    hr = method(enum, 4, HRESULT, C.c_int, C.c_int, POINTER(c_void_p))(enum, eRender, eConsole, byref(dev))
    release(enum)
    if hr < 0: return None, None
    meter = c_void_p()
    hr = method(dev, 3, HRESULT, POINTER(GUID), wintypes.DWORD, c_void_p, POINTER(c_void_p))(
            dev, byref(IID_IAudioMeterInformation), CLSCTX_ALL, None, byref(meter))
    if hr < 0: release(dev); return None, None
    return dev, meter

class PeakReader:
    def __init__(self):
        ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)  # STA, main thread, ONCE
        self.dev = self.meter = None
        self._rebuild()
    def _rebuild(self):
        release(self.meter); release(self.dev)
        self.dev, self.meter = build_meter()
    def read(self):                              # call from tkinter after() (main thread!)
        if not self.meter:
            self._rebuild()
            if not self.meter: return 0.0
        peak = c_float()
        hr = method(self.meter, 3, HRESULT, POINTER(c_float))(self.meter, byref(peak))
        if hr < 0: self._rebuild(); return 0.0   # incl. 0x88890004 device-invalidated -> rebuild
        return peak.value                        # 0.0..1.0
    def close(self):
        release(self.meter); release(self.dev)
        self.meter = self.dev = None
        ole32.CoUninitialize()
# tkinter: reader=PeakReader(); def tick(): update(reader.read()); root.after(40, tick)
#          root.protocol("WM_DELETE_WINDOW", lambda:(reader.close(), root.destroy()))
```

### Watch out for

- **Vtable slot indices are silent landmines.** `IAudioMeterInformation`: QI=0, AddRef=1, Release=2, **GetPeakValue=3**, GetMeteringChannelCount=4, GetChannelsPeakValues=5, QueryHardwareSupport=6. Hardcode them as named constants with a header citation.
- Build GUIDs via `CLSIDFromString`, never by hand-packing bytes (GUID fields are mixed-endian) — wrong bytes give `REGDB_E_CLASSNOTREG` / `E_NOINTERFACE`.
- **The meter is bound to the endpoint you activated.** On default-device switch it goes stale (returns last value, or `AUDCLNT_E_DEVICE_INVALIDATED` 0x88890004). Treat it as disposable: on any FAILED HRESULT, Release → `GetDefaultAudioEndpoint` → re-`Activate` (Microsoft's documented recovery). Also rebuild proactively every ~1–2 s to follow silent switches.
- A reading of **0.0 is legitimate silence** — and is the *expected* value during another app's exclusive-mode stream when the endpoint has no hardware meter. Don't infer "broken." Optionally check `QueryHardwareSupport` for `ENDPOINT_HARDWARE_SUPPORT_METER` (0x4).
- The endpoint meter is the **post-mix, all-apps-combined** instantaneous peak for the previous device period (~3–10 ms) — not per-session, not RMS. You don't need to enumerate sessions for a system-wide level. Smooth/decay yourself if desired.
- COM thread affinity: `CoInitializeEx(STA)` once on the main thread; do every call inside `after()` callbacks on that same thread. Cross-apartment calls give `RPC_E_WRONG_THREAD` or hang. Both `S_OK` and `S_FALSE` are success and each needs a matching `CoUninitialize`.
- ctypes does **not** auto-Release. Explicitly `Release` (slot 2) the device and meter on every rebuild and at shutdown; one balanced `CoUninitialize` after all interfaces are freed. Releasing the enumerator after activation is fine.
- `GetPeakValue` writes a C `float` (4 bytes). Use `c_float()` + `byref`, read `.value`; `pfPeak` must not be NULL (`E_POINTER`). Check `hr < 0` before trusting the value.

---

## 3. GetAsyncKeyState Hotkey Edge-Detection

### Do this

Poll the high bit only, on the GUI thread, with a rising-edge `was_down` flag for fire-once-no-repeat.

```python
import ctypes, tkinter as tk
user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype  = ctypes.c_short        # SHORT, not the default c_int

VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12         # generic = either L or R physical key

def is_down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)    # ONLY the 'currently down' high bit

class HotkeyPoller:
    def __init__(self, root, mods, key_char, callback, interval_ms=66):  # ~15 Hz
        self.root, self.mods, self.callback, self.interval = root, list(mods), callback, interval_ms
        self.key = ord(key_char.upper())                 # 'v' -> 0x56; there is NO VK_V constant
        self._was_down = False
        self._poll()
    def _combo_down(self):
        return all(is_down(m) for m in self.mods) and is_down(self.key)
    def _poll(self):
        try:
            now = self._combo_down()
            if now and not self._was_down:               # rising edge -> fire ONCE
                self._was_down = True                    # set before callback (reentrancy-safe)
                try: self.callback()
                except Exception: pass                   # never let a handler kill the loop
            elif not now:
                self._was_down = False                   # re-arm only after release
        finally:
            self.root.after(self.interval, self._poll)   # always reschedule, even on exception
# HotkeyPoller(root, [VK_CONTROL, VK_SHIFT], 'v', lambda: print("Ctrl+Shift+V!"))
```

### Watch out for

- Default ctypes restype is `c_int`, so the `SHORT` high bit is misread and naive truthiness (`if GetAsyncKeyState(vk):`) breaks. Set `restype = c_short` **and** mask with `& 0x8000` (the mask is correct regardless of restype).
- **Never** branch on the low bit `0x0001` ("pressed since last call"). MS says it is 16-bit-legacy and "should not be relied upon" — another process can consume it first (false negatives). Do edge detection in Python from the high bit instead.
- Without edge tracking you get **auto-repeat** (~15 fires/sec while held). The `was_down` rising-edge flag fixes this; it re-arms only when the chord is released.
- Polling **point-samples** — a tap shorter than the interval can be missed. 15 Hz (~66 ms) is fine for a held modifier chord; raise to ~50–60 Hz only if you need brief taps.
- Use **generic** modifier VKs (`VK_CONTROL`/`VK_SHIFT`/`VK_MENU`) so either L/R key works, matching user expectation. `VK_L*`/`VK_R*` only to pin a side. Note `VK_MENU` is Alt (the context-menu key is `VK_APPS` 0x5D).
- Letters/digits have **no** `VK_` constant: VK = uppercase ASCII (`ord('V')` == 0x56; A–Z = 0x41–0x5A, 0–9 = 0x30–0x39).
- `GetAsyncKeyState` can return 0 (inactive desktop / UIPI) — the `& 0x8000` mask treats that as "not down" safely. It is genuinely global (fires unfocused) but **cannot swallow** the keystroke from other apps, unlike `RegisterHotKey`/a low-level hook.
- Poll on the GUI thread via `after()` — tkinter is not thread-safe and the ctypes call is microsecond-fast.

---

## 4. Run-at-Startup via `pythonw` + HKCU Run Key (winreg)

### Do this

Resolve `pythonw.exe` from `sys.executable`, write one command string with each path independently quoted, and guard the std streams at process start.

```python
import os, sys, winreg
RUN_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "MyTkApp"                                   # the Run value NAME = stable identity handle

def _build_command():
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")  # anchor to running interp
    if not os.path.exists(pyw): pyw = sys.executable                    # fallback (may show console)
    script = os.path.abspath(__file__)                                  # absolute: cwd != our folder
    return f'"{pyw}" "{script}"'                                        # quote EACH path separately

def set_startup(enable=True):
    access = winreg.KEY_SET_VALUE | winreg.KEY_READ
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_SUBKEY, 0, access) as k:  # create-or-open
        if enable:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _build_command())
        else:
            try: winreg.DeleteValue(k, APP_NAME)
            except FileNotFoundError: pass             # already absent -> idempotent

def clear_startup(): set_startup(False)

def is_startup_enabled():
    try:
        with winreg.OpenKeyEx(winreg.HKEY_CURRENT_USER, RUN_SUBKEY, 0, winreg.KEY_READ) as k:
            val, typ = winreg.QueryValueEx(k, APP_NAME)
            return typ == winreg.REG_SZ and bool(val)
    except FileNotFoundError:
        return False

# --- at the VERY TOP of the GUI script, before any print/logging/import that may write to stderr ---
if sys.stdout is None: sys.stdout = open(os.devnull, "w")
if sys.stderr is None: sys.stderr = open(os.devnull, "w")   # better: a logfile under %LOCALAPPDATA%
if sys.stdin  is None: sys.stdin  = open(os.devnull, "r")
# and wrap main() in try/except that writes traceback to %LOCALAPPDATA%\APP_NAME\startup.log
```

### Watch out for

- Under `pythonw.exe` with no console (exactly the login scenario), `sys.stdout/stderr/stdin` are all **None**. Any `print`/traceback/`logging` StreamHandler raises `AttributeError` and silently kills the process. Guard the streams first; route real errors to a logfile.
- The Run value is **one command-line string**, not exe+args. Quote **each** path independently (`"{pyw}" "{script}"`) — an unquoted path with spaces is split by `CreateProcess` and never launches. Do not wrap the whole thing in one outer pair.
- Launched processes start with **cwd = `C:\Windows\System32`**, not your script folder. Resolve everything from `os.path.dirname(os.path.abspath(__file__))` or `%LOCALAPPDATA%`; relative paths in the Run value resolve against System32 and fail.
- Derive the interpreter from `sys.executable`'s directory — `sys.executable` itself is usually `python.exe` (console pops up at every login). Never use bare `python`/`py`/`pyw` or `shutil.which`: PATH may resolve to the **Microsoft Store alias stub** that prints "Python was not found." Verify the resolved `pythonw.exe` exists before writing.
- winreg exception types vary: query-missing → `FileNotFoundError(2)`; delete-missing read-only → `PermissionError(5)`; delete-missing with write access → `FileNotFoundError(2)`; open-missing-key → `FileNotFoundError(2)`. All subclass `OSError` — catch `FileNotFoundError` for is-enabled, treat missing as success for clear (idempotent).
- Use `REG_SZ` for a fully-resolved absolute command (`REG_EXPAND_SZ` only if you intentionally embed `%VAR%`). Keep the command under the **260-char** Run limit. Use `CreateKeyEx` (create-or-open) so a missing Run subkey on a minimal profile is handled.
- Target **HKCU** (per-user, no admin) — HKLM needs elevation. The OS may delay Run entries slightly at login, so absence of an instant launch isn't proof of breakage; verify with `reg query "HKCU\...\Run"` or Task Manager → Startup.

---

## 5. ctypes COM vtable Calling (no comtypes)

### Do this

Use ctypes' purpose-built COM-method prototype form — `prototype(vtbl_index, name)` auto-prepends `this` and indexes the vtable correctly for the platform. Use `oledll` so `restype = HRESULT` auto-raises on failure.

```python
import ctypes
from ctypes import wintypes, POINTER, byref, c_void_p, c_ulong, c_wchar_p, WINFUNCTYPE
ole32 = ctypes.oledll.ole32                            # oledll => HRESULT restype, auto-raises OSError

class GUID(ctypes.Structure):
    _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD),
                ('Data3', wintypes.WORD),  ('Data4', wintypes.BYTE * 8)]
    def __init__(self, s=None):
        super().__init__()
        if s is not None: ole32.CLSIDFromString(c_wchar_p(s), byref(self))

def com_method(vtbl_index, name, restype, *argtypes):
    proto = WINFUNCTYPE(restype, *argtypes)            # stdcall; DO NOT list 'this' yourself
    return proto(vtbl_index, name)                     # ctypes injects 'this', indexes vtable

# IUnknown indices are fixed; a derived interface's OWN methods start at index 3.
QueryInterface = com_method(0, 'QueryInterface', ctypes.HRESULT, POINTER(GUID), POINTER(c_void_p))
AddRef         = com_method(1, 'AddRef',  c_ulong)     # returns refcount, NOT an HRESULT
Release        = com_method(2, 'Release', c_ulong)

COINIT_APARTMENTTHREADED, CLSCTX_INPROC_SERVER = 0x2, 0x1
def call(method, iface, *args): return method(iface, *args)  # iface is the implicit 'this'

def example(clsid_str, iid_str):
    ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)     # once per thread; balance below
    try:
        clsid, iid = GUID(clsid_str), GUID(iid_str)
        obj = c_void_p()
        ole32.CoCreateInstance(byref(clsid), None, CLSCTX_INPROC_SERVER, byref(iid), byref(obj))
        try:
            other = c_void_p()
            call(QueryInterface, obj, byref(GUID('{....}')), byref(other))
            try: ...                                          # use 'other'
            finally: call(Release, other)                     # Release EVERY interface, incl. QI out
        finally:
            call(Release, obj)
    finally:
        ole32.CoUninitialize()                                # exactly one per CoInitializeEx
```

### Watch out for

- Prefer `prototype(vtbl_index, name)` over hand-rolling `WINFUNCTYPE(restype, c_void_p, ...)` + manually passing `this` — the docs' form auto-prepends `this` and indexes the vtable for the platform, eliminating off-by-one and pointer-stride bugs. (If you *do* walk the vtable manually, use `c_void_p`/`sizeof(c_void_p)` for stride — never `c_uint`/4-byte strides, which truncate on 64-bit. Layout is `POINTER(POINTER(c_void_p))`: `iface[0]` is the vtable, `vtable[i]` the method.)
- IUnknown indices are fixed (QI=0, AddRef=1, Release=2); a derived interface's first own method is index 3, then 4, 5… in C++ vtable order **including all inherited methods** (e.g. IDispatch's own methods start at 3 after QI/AddRef/Release, so a further-derived method starts after Invoke=6).
- Build the GUID with the exact field types (`DWORD, WORD, WORD, BYTE*8`) via `CLSIDFromString`/`IIDFromString` with the braces — wrong types match the wrong interface or fail.
- **HRESULT checking:** `S_OK==0` but `S_FALSE==1` is also success; severity is **bit 31**, not the sign of `hr != 0`. Easiest: `restype = ctypes.HRESULT` (via `oledll` or per-method) auto-raises `OSError` only on the severity bit. If checking manually: `FAILED = (hr & 0x80000000) != 0`.
- `CoInitializeEx`/`CoUninitialize` must balance **per thread** — including `S_FALSE` (already-initialized) returns, which still need a matching uninit. Re-initializing with a different concurrency flag returns `RPC_E_CHANGED_MODE`. Don't run `CoInitializeEx` through an auto-raising wrapper (it would treat `S_FALSE` oddly); use the raw `windll`/accept `hr in (0,1)`.
- ctypes does **not** refcount for you: `Release` (slot 2) **every** pointer from `CoCreateInstance`, `QueryInterface`, and out-params exactly once; wrap in try/finally; release interfaces before `CoUninitialize`. `AddRef`/`Release` return a `ULONG` count (`restype=c_ulong`), not an HRESULT.
- Optional pointer params: declare as `POINTER(T)`/`c_void_p` so `None` marshals as a NULL pointer; receive out-interfaces via `byref(c_void_p())`.
- Always **`WINFUNCTYPE` (stdcall), never `CFUNCTYPE`** — the bug hides on x64 (conventions converge) and crashes on x86. Use `ctypes.windll`/`ctypes.oledll`, never `cdll`.
- The Python 3.8–early-3.11 `Structure.from_param()` refcount regression (COM calls returning `None`) is **fixed in 3.12** — the project target is safe; still keep a strong ref to any by-value Structure for the call's duration.

---

## 6. Shell_NotifyIcon Tray Icon + Right-Click Menu

### Do this

Normal hidden top-level window (so it receives the `TaskbarCreated` broadcast), `WNDPROC` stored on the instance, `LRESULT = c_ssize_t`, all `.argtypes`/`.restype` set, `NOTIFYICONDATAW` with default alignment and `cbSize = sizeof(...)`.

```python
import ctypes, ctypes.wintypes as w
u32 = ctypes.WinDLL('user32', use_last_error=True)
shell = ctypes.WinDLL('shell32', use_last_error=True)
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
u32.DefWindowProcW.restype = LRESULT
u32.DefWindowProcW.argtypes = [w.HWND, w.UINT, w.WPARAM, w.LPARAM]

class GUID(ctypes.Structure):
    _fields_ = [('Data1', w.DWORD), ('Data2', w.WORD), ('Data3', w.WORD), ('Data4', ctypes.c_ubyte*8)]
class NOTIFYICONDATAW(ctypes.Structure):   # NO _pack_; default alignment matches the C ABI
    _fields_ = [('cbSize', w.DWORD), ('hWnd', w.HWND), ('uID', w.UINT), ('uFlags', w.UINT),
        ('uCallbackMessage', w.UINT), ('hIcon', w.HICON), ('szTip', w.WCHAR*128),
        ('dwState', w.DWORD), ('dwStateMask', w.DWORD), ('szInfo', w.WCHAR*256),
        ('uVersion', w.UINT), ('szInfoTitle', w.WCHAR*64), ('dwInfoFlags', w.DWORD),
        ('guidItem', GUID), ('hBalloonIcon', w.HICON)]
class WNDCLASSEX(ctypes.Structure):
    _fields_ = [('cbSize', w.UINT), ('style', w.UINT), ('lpfnWndProc', WNDPROC),
        ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int), ('hInstance', w.HINSTANCE),
        ('hIcon', w.HICON), ('hCursor', w.HANDLE), ('hbrBackground', w.HBRUSH),
        ('lpszMenuName', w.LPCWSTR), ('lpszClassName', w.LPCWSTR), ('hIconSm', w.HICON)]

WM_DESTROY, WM_COMMAND, WM_NULL, WM_RBUTTONUP = 2, 0x111, 0, 0x205
NIM_ADD, NIM_DELETE, NIM_SETVERSION = 0, 2, 4
NIF_MESSAGE, NIF_ICON, NIF_TIP = 1, 2, 4
CB, IDI_APPLICATION = WM_USER + 1 if (WM_USER := 0x400) else 0, 32512
TPM_RIGHTBUTTON, TPM_RETURNCMD = 2, 0x100

class TrayIcon:
    def __init__(self, tip='App', items=(('Quit', None),)):
        self.items, self._cmds = items, {}
        self._wndproc = WNDPROC(self._wnd_proc)            # KEEP REF on instance, else GC -> crash
        self.WM_TASKBARCREATED = u32.RegisterWindowMessageW('TaskbarCreated')
        hInst = ctypes.WinDLL('kernel32').GetModuleHandleW(None)
        self._wc = WNDCLASSEX(); self._wc.cbSize = ctypes.sizeof(WNDCLASSEX)
        self._wc.lpfnWndProc = self._wndproc; self._wc.hInstance = hInst
        self._wc.lpszClassName = 'PyTrayCls'
        u32.RegisterClassExW(ctypes.byref(self._wc))
        self.hwnd = u32.CreateWindowExW(0, 'PyTrayCls', 'PyTray', 0, 0, 0, 0, 0, 0, 0, hInst, 0)  # no ShowWindow -> stays invisible
        self.hicon = u32.LoadIconW(0, ctypes.c_wchar_p(IDI_APPLICATION))  # stock; do NOT DestroyIcon
        self.nid = NOTIFYICONDATAW(); self.nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)  # never hardcode
        self.nid.hWnd = self.hwnd; self.nid.uID = 1
        self.nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        self.nid.uCallbackMessage = CB; self.nid.hIcon = self.hicon; self.nid.szTip = tip
        self._add()
    def _add(self):
        shell.Shell_NotifyIconW(NIM_ADD, ctypes.byref(self.nid))
        self.nid.uVersion = 4; shell.Shell_NotifyIconW(NIM_SETVERSION, ctypes.byref(self.nid))
    def _wnd_proc(self, h, msg, wp, lp):
        if msg == self.WM_TASKBARCREATED: self._add(); return 0      # re-add after explorer restart
        if msg == CB:
            if (lp & 0xFFFF) in (WM_RBUTTONUP, 0x7B): self._menu()   # 0x7B = WM_CONTEXTMENU
            return 0
        if msg == WM_DESTROY: u32.PostQuitMessage(0); return 0
        return u32.DefWindowProcW(h, msg, wp, lp)
    def _menu(self):
        hm = u32.CreatePopupMenu(); self._cmds.clear()
        for i, (label, cb) in enumerate(self.items, 1):
            u32.AppendMenuW(hm, 0, i, label); self._cmds[i] = cb
        pt = w.POINT(); u32.GetCursorPos(ctypes.byref(pt))
        u32.SetForegroundWindow(self.hwnd)                           # REQUIRED before TrackPopupMenu
        cmd = u32.TrackPopupMenu(hm, TPM_RIGHTBUTTON | TPM_RETURNCMD, pt.x, pt.y, 0, self.hwnd, 0)
        u32.PostMessageW(self.hwnd, WM_NULL, 0, 0)                   # REQUIRED after
        u32.DestroyMenu(hm)
        if cmd and (cb := self._cmds.get(cmd)): cb()
    def run(self):                                                   # pump owns THIS thread
        msg = w.MSG()
        try:
            while u32.GetMessageW(ctypes.byref(msg), 0, 0, 0) > 0:
                u32.TranslateMessage(ctypes.byref(msg)); u32.DispatchMessageW(ctypes.byref(msg))
        finally: self.close()
    def close(self):
        shell.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self.nid))  # else ghost icon lingers
        u32.DestroyWindow(self.hwnd)
```

### Watch out for

- **Keep the `WNDPROC` wrapper alive** on a long-lived object (`self._wndproc = ...`) and keep the `WNDCLASSEX` instance alive too. ctypes doesn't reference it; GC → hard crash on the next dispatched message.
- **Pointer-sized types on Win64:** `WPARAM`/`LPARAM`/`LRESULT`/`HWND`/`HANDLE` are 8 bytes — `LONG` is 4. Define `LRESULT = c_ssize_t`, use the pointer-sized `wintypes`, and set `.argtypes`/`.restype` on **every** API (default `c_int` return truncates handles).
- **`NOTIFYICONDATAW` layout:** declare all Vista+ fields in order, do **not** set `_pack_` (let default alignment insert the padding the C ABI expects — `_pack_=1` makes `Shell_NotifyIconW` silently fail). Set `cbSize = ctypes.sizeof(...)` at runtime, never a hardcoded number.
- **Menu won't dismiss / sticks:** call `SetForegroundWindow(hwnd)` immediately *before* `TrackPopupMenu` and `PostMessageW(hwnd, WM_NULL, 0, 0)` immediately *after*. Use `TPM_RETURNCMD` so the selected id is returned directly; get coords from `GetCursorPos`.
- **Icon vanishes after Explorer restarts:** register `WM_TASKBARCREATED = RegisterWindowMessageW('TaskbarCreated')` and re-`NIM_ADD` (+ re-`NIM_SETVERSION`) when you receive it. This requires a **normal top-level window** — a message-only (`HWND_MESSAGE`) window does **not** receive broadcasts, so don't use one. Create the window and never call `ShowWindow`.
- **Callback packing is version-dependent.** With `NOTIFYICON_VERSION_4` (recommended, send `NIM_SETVERSION` after `NIM_ADD`): `LOWORD(lParam)` = event, `HIWORD(lParam)` = icon id, `GET_X/Y_LPARAM(wParam)` = anchor. Mask carefully (`& 0xFFFF`, `>> 16`) since values arrive pointer-sized. Switch on `LOWORD(lParam)`: `WM_CONTEXTMENU`(0x7B)/`WM_RBUTTONUP` → menu.
- **Clean up:** always `NIM_DELETE` on teardown (else a ghost icon lingers until hover), then `DestroyWindow`/`UnregisterClassW`; `PostQuitMessage(0)` from `WM_DESTROY` ends the loop. Stock icons from `LoadIconW(None, IDI_APPLICATION)` are shared — do **not** `DestroyIcon`; only `DestroyIcon` custom icons loaded with `LoadImageW(..., LR_LOADFROMFILE)`. Wrap in atexit/try-finally.
- **Thread affinity:** the tray window, its `WNDPROC`, and `GetMessageW` must all live on the **same** thread, and never call `Shell_NotifyIconW` from another thread. To combine with tkinter (which has its own pump), run `TrayIcon().run()` on a daemon thread and marshal actions back via `root.after()`/a queue.
