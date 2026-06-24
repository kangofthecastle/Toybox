"""Clipboard History + hotkey picker (Toybox Task 9).

A hidden tk controller polls the Windows clipboard sequence number (~4 Hz) and
records every text snippet into an in-memory ring buffer (no disk persistence).
A global hotkey (default Ctrl+Shift+V, ~15 Hz edge-detected poll) pops up a
dark, centered picker with type-to-filter, arrow-key navigation, and
Enter/double-click to re-copy the chosen entry. The picker is created on demand
and destroyed on close, so there is no idle UI cost.
"""
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import winkit.startup as startup
startup.guard_streams()  # MUST be the first executable statement (pythonw-at-login safety)

import tkinter as tk

import clip_history
import config
import winkit.input as wkinput

HERE = os.path.dirname(os.path.abspath(__file__))
CFG_PATH = os.path.join(HERE, "config.json")
LOG_PATH = os.path.join(HERE, "toybox.log")

# Clipboard change-poll cadence (Global Constraints: ~4 Hz).
CAPTURE_MS = 250

# Picker visual theme (dark).
BG = "#1e1f22"
FG = "#e8e8e8"
SEL_BG = "#3b6ea5"
SEL_FG = "#ffffff"
ENTRY_BG = "#2b2d31"
BORDER = "#4a4d52"
DIM = "#8a8d92"

MAX_ROWS = 10        # listbox height cap
LINE_CAP = 80        # max chars shown per entry
RETURN_GLYPH = "⏎"  # ⏎  shown where newlines were


def _smoke_ms():
    v = os.environ.get("TOYBOX_SMOKE")
    return int(v) if v else None


def _one_line(text):
    """Collapse a snippet to a single, length-capped display line."""
    flat = text.replace("\r\n", " ").replace("\r", " ").replace("\n", RETURN_GLYPH)
    flat = flat.replace("\t", " ").strip()
    if len(flat) > LINE_CAP:
        flat = flat[:LINE_CAP - 1] + "…"  # …
    return flat or RETURN_GLYPH


class ClipboardApp:
    def __init__(self, root, cfg):
        self.root = root
        self.cfg = cfg
        self.history = clip_history.ClipHistory(cfg["clipboard"]["max_items"])
        self.picker = None          # current Toplevel or None
        self.listbox = None
        self.entry = None
        self.filter_var = None
        self.visible = []           # list of (original_index, display_line) currently shown
        # Seed with the current sequence so the first real copy registers as a change.
        self._last_seq = wkinput.clipboard_sequence()
        self._poll_clipboard()
        # Global hotkey -> open picker.
        self.hotkey = wkinput.HotkeyPoller(
            root, cfg["clipboard"]["hotkey"], self.show_picker, 66
        )

    # -- clipboard capture loop -------------------------------------------
    def _poll_clipboard(self):
        try:
            seq = wkinput.clipboard_sequence()
            if seq != self._last_seq:
                self._last_seq = seq
                try:
                    text = self.root.clipboard_get()
                except tk.TclError:
                    text = None  # non-text clipboard (image/files) -> skip
                if text:
                    self.history.add(text)
        finally:
            self.root.after(CAPTURE_MS, self._poll_clipboard)

    # -- picker ------------------------------------------------------------
    def show_picker(self):
        # A picker is already open: destroy and reopen fresh so it reflects the
        # latest history and lands on top with focus.
        if self.picker is not None and self.picker.winfo_exists():
            self._close_picker()
        if len(self.history) == 0:
            return  # nothing to show

        win = tk.Toplevel(self.root)
        self.picker = win
        win.title("Clipboard")
        win.configure(bg=BORDER)
        win.overrideredirect(True)          # thin-bordered, chromeless look
        win.attributes("-topmost", True)

        # Inset frame creates a 1px border via the BORDER-colored toplevel bg.
        frame = tk.Frame(win, bg=BG)
        frame.pack(fill="both", expand=True, padx=1, pady=1)

        header = tk.Label(
            frame, text="Clipboard history  —  type to filter, Enter to paste",
            bg=BG, fg=DIM, anchor="w", font=("Segoe UI", 9),
        )
        header.pack(fill="x", padx=8, pady=(6, 2))

        self.filter_var = tk.StringVar()
        self.entry = tk.Entry(
            frame, textvariable=self.filter_var, bg=ENTRY_BG, fg=FG,
            insertbackground=FG, relief="flat", font=("Segoe UI", 11),
            highlightthickness=1, highlightbackground=BORDER,
            highlightcolor=SEL_BG,
        )
        self.entry.pack(fill="x", padx=8, pady=(0, 6), ipady=4)
        self.filter_var.trace_add("write", lambda *_: self._refresh_list())

        self.listbox = tk.Listbox(
            frame, bg=BG, fg=FG, selectbackground=SEL_BG, selectforeground=SEL_FG,
            relief="flat", highlightthickness=0, activestyle="none",
            font=("Consolas", 10), borderwidth=0, exportselection=False,
        )
        self.listbox.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self._refresh_list()

        # Key/mouse bindings on the picker.
        win.bind("<Escape>", lambda e: self._close_picker())
        self.entry.bind("<Down>", self._on_down)
        self.entry.bind("<Up>", self._on_up)
        self.entry.bind("<Return>", self._on_accept)
        self.listbox.bind("<Down>", self._on_down)
        self.listbox.bind("<Up>", self._on_up)
        self.listbox.bind("<Return>", self._on_accept)
        self.listbox.bind("<Double-Button-1>", self._on_accept)
        # Clicking away closes the picker.
        win.bind("<FocusOut>", self._on_focus_out)

        # Size + center on the screen the cursor is on (primary screen metrics).
        self._center(win)
        win.deiconify()
        win.lift()
        win.focus_force()
        # Type-to-filter is the primary interaction, so focus the entry; arrow
        # keys still move the listbox selection via the bindings above.
        self.entry.focus_set()

    def _center(self, win):
        rows = max(1, min(MAX_ROWS, len(self.visible) or len(self.history)))
        self.listbox.configure(height=rows)
        win.update_idletasks()
        w = 560
        h = win.winfo_reqheight()
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 3  # a touch above center reads better
        win.geometry(f"{w}x{h}+{x}+{y}")

    def _refresh_list(self):
        if self.listbox is None:
            return
        needle = (self.filter_var.get() if self.filter_var else "").lower()
        self.visible = []
        self.listbox.delete(0, tk.END)
        for idx, original in enumerate(self.history.items()):
            line = _one_line(original)
            if needle and needle not in original.lower():
                continue
            self.visible.append((idx, line))
            self.listbox.insert(tk.END, "  " + line)
        if self.visible:
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(0)
            self.listbox.activate(0)
            self.listbox.see(0)

    # -- navigation --------------------------------------------------------
    def _current_index(self):
        sel = self.listbox.curselection()
        return sel[0] if sel else -1

    def _move(self, delta):
        n = self.listbox.size()
        if n == 0:
            return
        cur = self._current_index()
        if cur < 0:
            cur = 0 if delta > 0 else n - 1
        else:
            cur = max(0, min(n - 1, cur + delta))
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(cur)
        self.listbox.activate(cur)
        self.listbox.see(cur)

    def _on_down(self, event):
        self._move(1)
        return "break"

    def _on_up(self, event):
        self._move(-1)
        return "break"

    def _on_accept(self, event):
        pos = self._current_index()
        if pos < 0 or pos >= len(self.visible):
            return "break"
        original_index, _ = self.visible[pos]
        text = self.history.items()[original_index]
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            # Re-copying our own value bumps the sequence; absorb it so the
            # capture loop does not treat the re-paste as a fresh entry.
            self._last_seq = wkinput.clipboard_sequence()
        except tk.TclError:
            pass
        self.history.select(original_index)
        self._close_picker()
        return "break"

    def _on_focus_out(self, event):
        # Only close if focus truly left the picker (not an internal child).
        if self.picker is None:
            return
        try:
            focused = self.picker.focus_get()
        except KeyError:
            focused = None
        if focused is None:
            self._close_picker()

    def _close_picker(self):
        win = self.picker
        self.picker = None
        self.listbox = None
        self.entry = None
        self.filter_var = None
        self.visible = []
        if win is not None:
            try:
                win.destroy()
            except tk.TclError:
                pass


def main():
    cfg = config.load(CFG_PATH)
    root = tk.Tk()
    root.withdraw()  # hidden controller; the picker is the only visible UI
    ClipboardApp(root, cfg)
    ms = _smoke_ms()
    if ms:
        # Root is never shown, so just schedule a clean exit for smoke mode.
        root.after(ms, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(traceback.format_exc() + "\n")
        except Exception:
            pass
        raise
