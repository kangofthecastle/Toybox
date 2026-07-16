"""The cat's Rotate-display panel: a small always-on-top window that turns the
physical monitor the cat is sitting on 90 degrees clockwise per click, cycling
0 -> 90 -> 180 -> 270 -> 0.

A right-click menu item can't do this well: a native popup menu dismisses the
moment you pick an entry, but rotating is a "click a few times until it looks
right, then stop" gesture. So the menu opens this panel instead and the panel
*stays open* until the user closes it (Done / Esc / the title-bar X).

Built on demand and reused as a singleton, mirroring petkit.settings; it is a
plain system-themed Toplevel (like the Settings window) so the buttons look
native. GUI glue only -- the native rotation lives in winkit.display and the
monitor pick in winkit.monitors. Every Tk call is guarded against TclError, like
the other cat windows. Stdlib only."""
import tkinter as tk

import winkit.monitors as monitors
import winkit.display as display


def _device_label(mon):
    """Short human label for a monitor: the DISPLAYn tail of the device name,
    plus a '(primary)' marker for the primary display."""
    tail = mon["device"].rsplit("\\", 1)[-1] or mon["device"]
    return tail + " (primary)" if mon.get("primary") else tail


class RotatePanel:
    def __init__(self, cat):
        self.cat = cat
        self.win = None
        self._status = None

    # --- lifecycle (singleton, mirrors petkit.settings) -----------------
    def open(self):
        """Show the panel, building it the first time; refresh the readout if it
        is already open."""
        if self.win is not None:
            try:
                self.win.deiconify(); self.win.lift(); self.win.focus_force()
                self._refresh()
                return
            except tk.TclError:
                self.win = None
        self._build()

    def close(self):
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
            self.win = None

    def _build(self):
        self.win = tk.Toplevel(self.cat.root)
        self.win.title("Cat · Rotate display")
        self.win.resizable(False, False)
        self.win.attributes("-topmost", True)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self.win.bind("<Escape>", lambda e: self.close())

        self._status = tk.Label(self.win, font=("Segoe UI", 11, "bold"))
        self._status.pack(padx=16, pady=(14, 2))
        tk.Label(self.win, text="Rotates the monitor the cat sits on.",
                 font=("Segoe UI", 8), fg="#666666").pack(padx=16, pady=(0, 10))

        row = tk.Frame(self.win)
        row.pack(padx=16, pady=(0, 14))
        tk.Button(row, text="⟳  Rotate 90°", width=14,
                  command=self._rotate).pack(side="left")
        tk.Button(row, text="Done", width=6,
                  command=self.close).pack(side="left", padx=(10, 0))

        self._refresh()
        self._place_near_cat()
        try:
            self.win.lift(); self.win.focus_force()
        except tk.TclError:
            pass

    def _place_near_cat(self):
        """Open centered on the monitor the cat is on, so it lands where the user
        is looking without covering the cat's typical bottom-of-screen perch."""
        try:
            self.win.update_idletasks()
            cx, cy = self._cat_center()
            w, h = self.win.winfo_width(), self.win.winfo_height()
            self.win.geometry("+%d+%d" % (cx - w // 2, cy - h - 20))
        except tk.TclError:
            pass

    # --- monitor pick + rotation ----------------------------------------
    def _cat_center(self):
        r = self.cat.root
        return (r.winfo_rootx() + r.winfo_width() // 2,
                r.winfo_rooty() + r.winfo_height() // 2)

    def _target(self):
        """The monitor the cat is currently sitting on (recomputed each call, so
        moving the cat retargets), or None if it can't be resolved."""
        cx, cy = self._cat_center()
        return monitors.monitor_at(cx, cy)

    def _rotate(self):
        mon = self._target()
        if not mon:
            self._set_status("No monitor found \U0001F431")
            return
        ok, orient = display.cycle_orientation(mon["device"])
        if ok:
            self._set_status("%s → %d°" % (_device_label(mon), orient * 90))
        else:
            self._set_status("%s · rotation failed" % _device_label(mon))

    def _refresh(self):
        mon = self._target()
        if not mon:
            self._set_status("No monitor found \U0001F431")
            return
        orient = display.orientation(mon["device"])
        deg = "?" if orient is None else "%d°" % (orient * 90)
        self._set_status("%s · %s" % (_device_label(mon), deg))

    def _set_status(self, text):
        if self._status is not None:
            try:
                self._status.configure(text=text)
            except tk.TclError:
                pass
