"""Fixed-drive free-space sensor + pure formatting helpers for the HUD's
one-line disk row. Guarded ctypes on kernel32 -- never raises. Pure stdlib."""


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
