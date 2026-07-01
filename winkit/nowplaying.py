"""Now-playing reader for the current Windows System Media Transport Controls
(SMTC) session, via WinRT through ctypes. read() returns a NowPlaying snapshot
or None and NEVER raises, on any machine (no session, WinRT missing, COM error).
Also holds pure, unit-tested helpers the HUD uses to animate the progress bar
smoothly between reads. Pure Python 3.12 stdlib -- no pip."""
from collections import namedtuple

NowPlaying = namedtuple(
    "NowPlaying", "title artist status position_s duration_s sampled_at")


def progress_fraction(position_s, duration_s):
    """Fraction played in [0, 1]. 0.0 when duration is non-positive/invalid or
    the position is non-positive; 1.0 when the position meets/exceeds duration."""
    try:
        d = float(duration_s)
        p = float(position_s)
    except (TypeError, ValueError):
        return 0.0
    if d <= 0 or p <= 0:
        return 0.0
    if p >= d:
        return 1.0
    return p / d


def advance(position_s, elapsed_s, status):
    """Displayed position after `elapsed_s` wall-clock seconds. Adds elapsed only
    while playing; holds otherwise. Never returns a negative number."""
    try:
        p = float(position_s)
    except (TypeError, ValueError):
        p = 0.0
    if status == "playing":
        try:
            e = float(elapsed_s)
        except (TypeError, ValueError):
            e = 0.0
        if e > 0:
            p += e
    return p if p > 0 else 0.0


def format_track(title, artist):
    """'title — artist'; title alone when artist empty; artist alone when
    title empty; '' when both empty. Whitespace-trimmed."""
    t = (title or "").strip()
    a = (artist or "").strip()
    if t and a:
        return "%s — %s" % (t, a)
    return t or a
