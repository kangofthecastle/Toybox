"""Load a horizontal sprite sheet (PNG) into cached, nearest-neighbor-zoomed
Tk frames. Pure rendering glue: one PhotoImage per (frame, zoom). Binary-alpha
PNGs only (the cat pack), so frames need no alpha compositing. Tk 8.6+ (PNG)."""
import tkinter as tk


def opaque_bbox(w, h, is_opaque):
    """Smallest (minx, miny, maxx, maxy) (inclusive) covering every cell for
    which is_opaque(x, y) is True, scanning the w x h grid. Returns None if no
    cell is opaque. Pure — the caller supplies the opacity predicate."""
    minx = miny = None
    maxx = maxy = -1
    for y in range(h):
        for x in range(w):
            if is_opaque(x, y):
                if minx is None or x < minx:
                    minx = x
                if miny is None or y < miny:
                    miny = y
                if x > maxx:
                    maxx = x
                if y > maxy:
                    maxy = y
    if minx is None:
        return None
    return (minx, miny, maxx, maxy)


class SpriteSheet:
    def __init__(self, master, path, frame_w=32, frame_h=32):
        self._master = master
        self._sheet = tk.PhotoImage(master=master, file=path)
        self.frame_w = frame_w
        self.frame_h = frame_h
        self.frame_count = self._sheet.width() // frame_w
        self._cache = {}

    def frame(self, index, zoom=1):
        index %= self.frame_count
        key = (index, zoom)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        fw, fh = self.frame_w, self.frame_h
        cell = tk.PhotoImage(master=self._master, width=fw, height=fh)
        x0 = index * fw
        # 'set' compositing copies source pixels (incl. alpha) verbatim.
        cell.tk.call(str(cell), "copy", str(self._sheet),
                     "-from", x0, 0, x0 + fw, fh, "-to", 0, 0,
                     "-compositingrule", "set")
        img = cell.zoom(zoom) if zoom > 1 else cell
        self._cache[key] = img
        return img

    def opaque_bounds(self, index):
        """(minx, miny, maxx, maxy) of the opaque pixels in the unzoomed frame,
        or None if fully transparent. Lets UI anchor to the cat's real silhouette
        instead of its transparent-padded 32x32 cell."""
        cell = self.frame(index, 1)
        return opaque_bbox(self.frame_w, self.frame_h,
                           lambda x, y: not cell.transparency_get(x, y))
