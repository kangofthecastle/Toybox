"""Master-volume control for the default Windows playback (render) endpoint via
Core Audio (IAudioEndpointVolume) through ctypes. get()/set_level()/set_mute()/
toggle_mute() are blanket-guarded and NEVER raise on any machine (no device, COM
error, non-Windows). Also holds the pure UI-math helpers the HUD slider uses.
Pure Python 3.12 stdlib -- no pip."""


def clamp01(x):
    """x coerced into [0.0, 1.0]; 0.0 on bad input."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if v <= 0.0:
        return 0.0
    if v >= 1.0:
        return 1.0
    return v


def level_from_x(x, x_left, x_right):
    """Fraction in [0,1] for a click/drag at pixel x on a track spanning
    [x_left, x_right]. 0.0 for a degenerate/backwards track or bad input."""
    try:
        x = float(x); lo = float(x_left); hi = float(x_right)
    except (TypeError, ValueError):
        return 0.0
    if hi <= lo:
        return 0.0
    return clamp01((x - lo) / (hi - lo))


def x_from_level(level, x_left, x_right):
    """Knob pixel-x for `level` on a track spanning [x_left, x_right]."""
    try:
        lo = int(x_left); hi = int(x_right)
    except (TypeError, ValueError):
        return 0
    return lo + int((hi - lo) * clamp01(level))


def format_pct(level):
    """'63%' for a level; '' for None."""
    if level is None:
        return ""
    return "%d%%" % round(clamp01(level) * 100)


def step_level(level, delta):
    """level + delta, clamped to [0,1]."""
    try:
        base = float(level)
    except (TypeError, ValueError):
        base = 0.0
    try:
        d = float(delta)
    except (TypeError, ValueError):
        d = 0.0
    return clamp01(base + d)
