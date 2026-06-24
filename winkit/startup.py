"""pythonw stream guard + run-at-startup (HKCU Run) via winreg. See gotchas section 4."""
import os
import sys
import winreg

RUN_SUBKEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


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
