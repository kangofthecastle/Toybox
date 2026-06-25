"""Pre-baked radial glow sprites for the pet: a soft disc fading from a hue at
the center to the overlay key color at the rim (so the rim is the key color =
transparent on the color-key window -- no alpha needed, no fringe). Built once
per (quantized hue, level) and cached. `glow_pixel` is the pure gradient (unit-
tested); the PhotoImage assembly needs Tk and runs at startup / lazily."""
import tkinter as tk


def glow_pixel(dist, radius, hue, key, level):
    """(r,g,b) at `dist` from center: hue*level at center fading to `key` at the
    rim (>= radius). `level` 0..1 scales peak brightness toward the hue."""
    if radius <= 0:
        return tuple(key)
    t = dist / radius
    if t >= 1.0:
        return tuple(key)
    k = ((1.0 - t) ** 2) * level
    return tuple(int(round(key[c] + (hue[c] - key[c]) * k)) for c in range(3))


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
        img = tk.PhotoImage(master=self._master, width=n, height=n)
        rows = []
        for y in range(n):
            cells = []
            dy2 = (y - r) ** 2
            for x in range(n):
                d = (((x - r) ** 2) + dy2) ** 0.5
                rr, gg, bb = glow_pixel(d, r, hue, self._key, level)
                cells.append("#%02x%02x%02x" % (rr, gg, bb))
            rows.append("{" + " ".join(cells) + "}")
        img.put(" ".join(rows))
        return img
