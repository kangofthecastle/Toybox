"""Pre-baked radial glow sprites for the pet: an ordered-dithered (Bayer 4x4)
stipple that fades from a bright hue at the center to FULLY TRANSPARENT by
DOT DENSITY -- so the aura dissolves into the color-key background instead of
sitting on an opaque dark disc. Built once per (quantized hue, level) and cached.

`glow_coverage` (the density profile) and `_lit` (the dither test) are pure and
unit-tested; the PhotoImage assembly needs Tk and runs at startup / lazily."""
import tkinter as tk

# Ordered 4x4 Bayer thresholds. A cell is lit when the local glow coverage
# exceeds its threshold, so coverage maps to dot DENSITY (a fake alpha that the
# color-key overlay can actually show: lit = glow color, unlit = key = clear).
_BAYER = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))


def glow_coverage(dist, radius, level):
    """Dot density in [0,1] at `dist` from the center: peaks at the center with a
    squared falloff to 0 at the rim (>= radius), scaled (and pulsed) by `level`."""
    if radius <= 0:
        return 0.0
    t = dist / radius
    if t >= 1.0:
        return 0.0
    return min(1.0, ((1.0 - t) ** 2) * 1.7 * level)


def _lit(x, y, coverage):
    """True if the dither cell at (x, y) is lit for the given coverage."""
    return coverage > (_BAYER[y & 3][x & 3] + 0.5) / 16.0


class GlowCache:
    def __init__(self, master, key_rgb, size=140, levels=6):
        self._master = master
        self._key = tuple(key_rgb)
        self._size = size
        self._levels = max(2, levels)
        self._cache = {}

    def get(self, hue, level):
        lv = int(round(max(0.0, min(1.0, level)) * (self._levels - 1)))
        hq = tuple((c // 16) * 16 for c in hue)   # quantize to bound cache size
        ckey = (hq, lv)
        hit = self._cache.get(ckey)
        if hit is not None:
            return hit
        img = self._build(hq, lv / (self._levels - 1))
        self._cache[ckey] = img
        return img

    def _build(self, hue, level):
        n = self._size
        r = n / 2.0
        key_hex = "#%02x%02x%02x" % self._key
        # One uniform, bright dot color (a touch brighter as the music swells);
        # the fade to transparent is carried entirely by dot density, so there is
        # no dim opaque ring -- unlit cells are the key color (clear).
        b = min(1.0, 0.55 + 0.45 * level)
        on_hex = "#%02x%02x%02x" % tuple(
            int(round(self._key[c] + (hue[c] - self._key[c]) * b)) for c in range(3))
        img = tk.PhotoImage(master=self._master, width=n, height=n)
        rows = []
        for y in range(n):
            dy2 = (y - r) ** 2
            cells = []
            for x in range(n):
                d = (((x - r) ** 2) + dy2) ** 0.5
                cells.append(on_hex if _lit(x, y, glow_coverage(d, r, level)) else key_hex)
            rows.append("{" + " ".join(cells) + "}")
        img.put(" ".join(rows))
        return img
