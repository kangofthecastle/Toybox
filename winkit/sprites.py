"""Load a horizontal sprite sheet (PNG) into cached, nearest-neighbor-zoomed
Tk frames. Pure rendering glue: one PhotoImage per (frame, zoom). Binary-alpha
PNGs only (the cat pack), so frames need no alpha compositing. Tk 8.6+ (PNG)."""
import tkinter as tk


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
