"""Fixed-drive free-space sensor + pure formatting helpers for the HUD's
one-line disk row. Guarded ctypes on kernel32 -- never raises. Pure stdlib."""
import ctypes
import shutil
import string

try:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
    _kernel32.GetDriveTypeW.restype = ctypes.c_uint
except Exception:
    _kernel32 = None   # non-Windows / load failure: enumeration yields []

DRIVE_FIXED = 3


def _drive_type(root):
    """Single ctypes call (the test seam). Returns the Win32 drive-type code, or
    -1 on any failure so the caller simply skips that letter."""
    if _kernel32 is None:
        return -1
    try:
        return _kernel32.GetDriveTypeW(root)
    except Exception:
        return -1


def fixed_drives():
    """Local fixed drives as 'C:' strings, in A..Z order. Never raises; any
    failure yields the drives found so far (possibly [])."""
    drives = []
    try:
        for letter in string.ascii_uppercase:
            if _drive_type("%s:\\" % letter) == DRIVE_FIXED:
                drives.append("%s:" % letter)
    except Exception:
        pass
    return drives


def usage():
    """(letter, free_bytes, total_bytes) per fixed drive via shutil.disk_usage,
    guarded per drive so one unreadable volume can't sink the row. Never raises."""
    out = []
    for letter in fixed_drives():
        try:
            u = shutil.disk_usage(letter + "\\")
            out.append((letter, int(u.free), int(u.total)))
        except Exception:
            pass
    return out


def human_bytes(n):
    """Compact free-space label, at most 4 chars: '0', '999M', '312G', '1.1T'.
    1024-based; rolls to the next unit before the number could reach 1000 so the
    output can never exceed four characters. Non-numeric/negative -> '0'."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "0"
    if n < 0:
        n = 0
    units = ["", "K", "M", "G", "T", "P"]
    size = float(n)
    idx = 0
    while size >= 1000 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    unit = units[idx]
    if not unit:
        return "%d" % int(size)
    if size < 9.95:
        return "%.1f%s" % (size, unit)
    return "%.0f%s" % (size, unit)


def format_disk_row(usages, max_chars):
    """Pack (letter, free_bytes, total_bytes) tuples into one line:
    'C 312G  D 1.1T'. The drive letter's trailing ':' is dropped. Truncates with
    a trailing '…' when the packed line exceeds max_chars (None = no cap)."""
    parts = []
    for letter, free, _total in usages:
        label = letter.rstrip(":") if isinstance(letter, str) else str(letter)
        parts.append("%s %s" % (label, human_bytes(free)))
    row = "  ".join(parts)
    if max_chars is not None and len(row) > max_chars:
        row = row[:max_chars - 1] + "…"
    return row
