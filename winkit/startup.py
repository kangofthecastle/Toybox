"""pythonw stream guard + run-at-startup (HKCU Run) via winreg. See gotchas section 4."""
import ctypes
from ctypes import wintypes
import os
import sys
import winreg

RUN_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

# --- single-instance guard (named mutex) ---------------------------------
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.OpenMutexW.restype = wintypes.HANDLE
_kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.OpenEventW.restype = wintypes.HANDLE
_kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.SetEvent.argtypes = [wintypes.HANDLE]
_kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]

_ERROR_ALREADY_EXISTS = 183
_SYNCHRONIZE = 0x00100000
_EVENT_MODIFY_STATE = 0x0002
_WAIT_OBJECT_0 = 0x00000000
_held_handles = []  # keep handles (mutexes, events) alive for the life of the process
_held_mutexes = _held_handles  # backwards-compatible alias


def acquire_single_instance(name):
    """Become the sole instance identified by `name`. Returns True if acquired
    (no other instance is running), False if one already exists. On failure to
    create the mutex at all, returns True (never block a toy from starting)."""
    handle = _kernel32.CreateMutexW(None, False, "Local\\" + name)
    if not handle:
        return True
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(handle)
        return False
    _held_mutexes.append(handle)
    return True


def is_instance_running(name):
    """True if some process currently holds the single-instance mutex `name`."""
    handle = _kernel32.OpenMutexW(_SYNCHRONIZE, False, "Local\\" + name)
    if handle:
        _kernel32.CloseHandle(handle)
        return True
    return False


# --- cross-instance quit signal (named manual-reset event) ----------------
# A toy can't be stopped just by the process handle the launcher happens to
# hold: toys started at login (or by a previous launcher) are orphans the
# launcher never owned. So each toy creates a named quit event and polls it;
# the launcher (or anyone) can signal that event by name to ask it to exit.

def create_quit_event(name):
    """Create this instance's quit event and return a handle to poll with
    quit_requested(). Reset to non-signalled even if the name pre-existed.
    Returns None on failure (the toy then simply has no remote-quit channel)."""
    handle = _kernel32.CreateEventW(None, True, False, "Local\\" + name + "_quit")
    if not handle:
        return None
    _kernel32.ResetEvent(handle)        # guard against a stale signalled state
    _held_handles.append(handle)        # keep alive for the life of the process
    return handle


def quit_requested(handle):
    """True once some process has called signal_quit() for this event."""
    if not handle:
        return False
    return _kernel32.WaitForSingleObject(handle, 0) == _WAIT_OBJECT_0


def signal_quit(name):
    """Ask the instance identified by `name` to quit (set its quit event).
    Returns True if a listening instance was found and signalled, else False."""
    handle = _kernel32.OpenEventW(_EVENT_MODIFY_STATE, False, "Local\\" + name + "_quit")
    if not handle:
        return False
    _kernel32.SetEvent(handle)
    _kernel32.CloseHandle(handle)
    return True


def watch_for_quit(name, schedule, on_quit, interval_ms=400):
    """Register this instance's quit event and poll it via `schedule` (a
    callable like Tk's root.after: schedule(ms, callback)). When another
    process signals the quit, call on_quit() (e.g. root.destroy). tk-agnostic
    so it stays unit-testable. Returns the event handle."""
    handle = create_quit_event(name)

    def _poll():
        if quit_requested(handle):
            on_quit()
        else:
            schedule(interval_ms, _poll)

    schedule(interval_ms, _poll)
    return handle


def guard_streams():
    """Replace any None std stream (the pythonw-at-login case) with os.devnull so a
    stray print/traceback can't raise AttributeError and silently kill the process."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    if sys.stdin is None:
        sys.stdin = open(os.devnull, "r")


def _pythonw():
    candidate = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return candidate if os.path.exists(candidate) else sys.executable


def pythonw_command(script_path):
    """Build a Run-value command: pythonw.exe and the absolute script path, each
    quoted independently so paths with spaces survive CreateProcess splitting."""
    return f'"{_pythonw()}" "{os.path.abspath(script_path)}"'


def set_run_at_startup(name, script_path, enabled):
    """Add (enabled) or remove (disabled) an HKCU Run entry. Idempotent."""
    access = winreg.KEY_SET_VALUE | winreg.KEY_READ
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_SUBKEY, 0, access) as key:
        if enabled:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, pythonw_command(script_path))
        else:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass


def is_run_at_startup(name):
    try:
        with winreg.OpenKeyEx(winreg.HKEY_CURRENT_USER, RUN_SUBKEY, 0, winreg.KEY_READ) as key:
            val, typ = winreg.QueryValueEx(key, name)
            return typ == winreg.REG_SZ and bool(val)
    except FileNotFoundError:
        return False
