"""Zone math: split a monitor work area into two rects, hit-test, divider moves.

Rects are Win32-style (left, top, right, bottom) tuples in physical pixels;
``right``/``bottom`` are exclusive. Layouts: "v" (left/right) or "h" (top/bottom).
Pure functions only — no Tk, no ctypes.
"""

RATIO_MIN = 0.15
RATIO_MAX = 0.85
LAYOUTS = ("off", "v", "h")


def clamp_ratio(ratio):
    """Clamp a split ratio into [RATIO_MIN, RATIO_MAX]; bad input -> 0.5."""
    try:
        r = float(ratio)
    except (TypeError, ValueError):
        return 0.5
    if r != r:  # NaN
        return 0.5
    return min(RATIO_MAX, max(RATIO_MIN, r))


def zone_rects(work, layout, ratio):
    """The two zone rects tiling `work` exactly (no gap, no overlap).

    Zone 0 is left ("v") or top ("h"); zone 1 gets the remainder, so the two
    rects always reassemble into `work` regardless of rounding.
    """
    left, top, right, bottom = work
    r = clamp_ratio(ratio)
    if layout == "v":
        split = left + round((right - left) * r)
        return [(left, top, split, bottom), (split, top, right, bottom)]
    if layout == "h":
        split = top + round((bottom - top) * r)
        return [(left, top, right, split), (left, split, right, bottom)]
    raise ValueError(f"no zones for layout {layout!r}")


def zone_at(work, layout, ratio, x, y):
    """Index (0 or 1) of the zone containing screen point, or None if outside
    `work` or the layout is off."""
    if layout not in ("v", "h"):
        return None
    left, top, right, bottom = work
    if not (left <= x < right and top <= y < bottom):
        return None
    zone0 = zone_rects(work, layout, ratio)[0]
    if layout == "v":
        return 0 if x < zone0[2] else 1
    return 0 if y < zone0[3] else 1


def divider_pos(work, layout, ratio):
    """The divider coordinate: an x for "v", a y for "h"."""
    zone0 = zone_rects(work, layout, ratio)[0]
    return zone0[2] if layout == "v" else zone0[3]


def ratio_from_point(work, layout, x, y):
    """The clamped ratio that puts the divider at screen point (x, y)."""
    left, top, right, bottom = work
    if layout == "v":
        span, offset = (right - left), (x - left)
    elif layout == "h":
        span, offset = (bottom - top), (y - top)
    else:
        raise ValueError(f"no divider for layout {layout!r}")
    if span <= 0:
        return 0.5
    return clamp_ratio(offset / span)


def next_layout(layout):
    """Cycle off -> v -> h -> off (unknown values reset to off)."""
    try:
        return LAYOUTS[(LAYOUTS.index(layout) + 1) % len(LAYOUTS)]
    except ValueError:
        return "off"
