"""The cat's Settings window: a normal (titled, movable) Toplevel hosting a
ttk.Notebook with Focus / Reminders / Pin / More tabs. Built on demand and
reused as a singleton; reads/writes the live cfg and calls back into Cat for
actions. GUI glue only -- the testable logic lives in petkit.reminders and
winkit.window. Guards every after()/refresh against TclError like bubble.py."""
import time
import tkinter as tk
from tkinter import ttk

import petkit.reminders as reminders
import winkit.window as window

_MORE_TOGGLES = (
    ("petting", "Petting & purr"),
    ("catnap", "Box catnap"),
    ("greeter", "Welcome-back greeting"),
    ("nudges", "Break nudges"),
    ("carry", "Catch & carry files"),
)


class SettingsWindow:
    def __init__(self, cat):
        self.cat = cat
        self.win = None
        self._nb = None
        self._tabs = {}
        self._after = None

    # --- lifecycle ------------------------------------------------------
    def open(self, tab=None):
        if self.win is not None:
            try:
                self.win.deiconify(); self.win.lift(); self.win.focus_force()
            except tk.TclError:
                self.win = None
        if self.win is None:
            self._build()
        if tab is not None and tab in self._tabs:
            try:
                self._nb.select(self._tabs[tab])
            except tk.TclError:
                pass

    def close(self):
        if self._after is not None:
            try:
                self.win.after_cancel(self._after)
            except Exception:
                pass
            self._after = None
        if self.win is not None:
            try:
                self.win.destroy()
            except tk.TclError:
                pass
            self.win = None

    def _build(self):
        self.win = tk.Toplevel(self.cat.root)
        self.win.title("Cat · Settings")
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._nb = ttk.Notebook(self.win)
        self._nb.pack(fill="both", expand=True, padx=8, pady=8)
        self._tabs = {}
        self._build_focus_tab()
        self._build_reminders_tab()
        self._build_pin_tab()
        self._build_more_tab()
        self._refresh_reminders()
        self._refresh_pins()
        self._tick_remaining()

    def _add_tab(self, name):
        frame = tk.Frame(self._nb)
        self._nb.add(frame, text=name)
        self._tabs[name] = frame
        return frame

    # --- Focus tab ------------------------------------------------------
    def _build_focus_tab(self):
        f = self._add_tab("Focus")
        pet = self.cat.cfg["pet"]
        self._focus_var = tk.StringVar(value=str(pet.get("focus_min", 25)))
        self._break_var = tk.StringVar(value=str(pet.get("break_min", 5)))
        self._focus_status = tk.StringVar(value="")
        row = tk.Frame(f); row.pack(anchor="w", padx=10, pady=(10, 4))
        tk.Label(row, text="Focus").pack(side="left")
        tk.Spinbox(row, from_=1, to=600, width=4, textvariable=self._focus_var).pack(side="left", padx=(4, 2))
        tk.Label(row, text="min   Break").pack(side="left")
        tk.Spinbox(row, from_=1, to=120, width=4, textvariable=self._break_var).pack(side="left", padx=(4, 2))
        tk.Label(row, text="min").pack(side="left")
        tk.Button(row, text="Save", command=self._on_save_focus).pack(side="left", padx=8)
        tk.Label(f, textvariable=self._focus_status, fg="#3a7").pack(anchor="w", padx=10)
        ctl = tk.Frame(f); ctl.pack(anchor="w", padx=10, pady=8)
        tk.Button(ctl, text="▶ Start", command=self.cat._start_focus).pack(side="left")
        tk.Button(ctl, text="⏸ Pause", command=self.cat._pause_focus).pack(side="left", padx=4)
        tk.Button(ctl, text="▶ Resume", command=self.cat._resume_focus).pack(side="left")
        tk.Button(ctl, text="■ Stop", command=self.cat._stop_focus).pack(side="left", padx=4)
        self._remaining_var = tk.StringVar(value="idle")
        tk.Label(f, textvariable=self._remaining_var).pack(anchor="w", padx=10, pady=(0, 10))

    def _on_save_focus(self):
        try:
            fm, bm = int(self._focus_var.get()), int(self._break_var.get())
        except (TypeError, ValueError):
            self._focus_status.set("enter whole minutes"); return
        if fm <= 0 or bm <= 0:
            self._focus_status.set("minutes must be > 0"); return
        self.cat._set_focus_minutes(fm, bm)
        self._focus_status.set("saved ✓")

    def _tick_remaining(self):
        if self.win is None:
            return
        st = self.cat.pomodoro.state
        if st in ("focus", "break", "paused"):
            rem = int(max(0, self.cat.pomodoro.remaining(time.monotonic())))
            self._remaining_var.set("%s  %d:%02d" % (st, rem // 60, rem % 60))
        else:
            self._remaining_var.set("idle")
        try:
            self._after = self.win.after(500, self._tick_remaining)
        except tk.TclError:
            self._after = None

    # --- Reminders tab --------------------------------------------------
    def _build_reminders_tab(self):
        f = self._add_tab("Reminders")
        pet = self.cat.cfg["pet"]
        self._rem_enable = tk.IntVar(value=1 if pet.get("reminders", True) else 0)
        tk.Checkbutton(f, text="Enable reminders", variable=self._rem_enable,
                       command=lambda: self.cat._set_cfg_flag("reminders", self._rem_enable.get())
                       ).pack(anchor="w", padx=10, pady=(8, 2))
        self._msg_var = tk.StringVar()
        self._mode_var = tk.StringVar(value="in")
        self._amount_var = tk.StringVar(value="20")
        self._unit_var = tk.StringVar(value="min")
        self._hh_var = tk.StringVar(value="9")
        self._mm_var = tk.StringVar(value="00")
        self._rem_status = tk.StringVar(value="")
        mrow = tk.Frame(f); mrow.pack(anchor="w", padx=10, pady=2)
        tk.Label(mrow, text="Message").pack(side="left")
        tk.Entry(mrow, width=26, textvariable=self._msg_var).pack(side="left", padx=4)
        inrow = tk.Frame(f); inrow.pack(anchor="w", padx=10, pady=2)
        tk.Radiobutton(inrow, text="in", variable=self._mode_var, value="in").pack(side="left")
        tk.Spinbox(inrow, from_=0, to=999, width=4, textvariable=self._amount_var).pack(side="left", padx=2)
        tk.OptionMenu(inrow, self._unit_var, "min", "hours").pack(side="left")
        atrow = tk.Frame(f); atrow.pack(anchor="w", padx=10, pady=2)
        tk.Radiobutton(atrow, text="at", variable=self._mode_var, value="at").pack(side="left")
        tk.Spinbox(atrow, from_=0, to=23, width=3, textvariable=self._hh_var).pack(side="left", padx=2)
        tk.Label(atrow, text=":").pack(side="left")
        tk.Spinbox(atrow, from_=0, to=59, width=3, textvariable=self._mm_var).pack(side="left", padx=2)
        self._repeat_var = tk.IntVar(value=0)
        tk.Checkbutton(atrow, text="daily", variable=self._repeat_var).pack(side="left", padx=(8, 0))
        tk.Button(atrow, text="Add", command=self._on_add_reminder).pack(side="left", padx=8)
        tk.Label(f, textvariable=self._rem_status, fg="#c33").pack(anchor="w", padx=10)
        tk.Frame(f, height=1, bg="#ccc").pack(fill="x", padx=10, pady=4)
        self._rem_list = tk.Frame(f)
        self._rem_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _on_add_reminder(self):
        mode = self._mode_var.get()
        if mode == "in":
            due = reminders.due_from_fields("in", self._amount_var.get(),
                                            self._unit_var.get(), 0, 0, time.time())
        else:
            due = reminders.due_from_fields("at", 0, "min",
                                            self._hh_var.get(), self._mm_var.get(), time.time())
        if due is None:
            self._rem_status.set("couldn't read that time"); return
        self._rem_status.set("")
        repeat = "daily" if self._repeat_var.get() else "none"
        self.cat.reminders.add(self._msg_var.get().strip() or "Reminder", due, repeat)
        self._msg_var.set("")
        self._refresh_reminders()

    def _refresh_reminders(self):
        if self.win is None:
            return
        for w in self._rem_list.winfo_children():
            w.destroy()
        pending = self.cat.reminders.pending()
        if not pending:
            tk.Label(self._rem_list, text="(no reminders)", fg="#888").pack(anchor="w")
            return
        now = time.time()
        for item in pending:
            row = tk.Frame(self._rem_list); row.pack(fill="x", pady=1)
            tk.Button(row, text="✕", width=2,
                      command=lambda it=item: self._remove_reminder(it)).pack(side="right")
            daily = item.get("repeat") == "daily"
            when = ("daily " if daily else "") + reminders.format_due(item["due"], now)
            tk.Label(row, text=when, fg="#666").pack(side="right", padx=6)
            tk.Label(row, text=("↻ " if daily else "• ") + item["text"], anchor="w").pack(side="left")

    def _remove_reminder(self, item):
        self.cat.reminders.remove(item["text"], item["due"])
        self._refresh_reminders()

    # --- Pin tab --------------------------------------------------------
    def _build_pin_tab(self):
        f = self._add_tab("Pin")
        pet = self.cat.cfg["pet"]
        self._pin_enable = tk.IntVar(value=1 if pet.get("pin", True) else 0)
        tk.Checkbutton(f, text="Enable pin", variable=self._pin_enable,
                       command=lambda: self.cat._set_cfg_flag("pin", self._pin_enable.get())
                       ).pack(anchor="w", padx=10, pady=(8, 2))
        tk.Label(f, text="Move the cat over a window, then use “Pin this window” "
                         "(right-click the cat or the button below).",
                 wraplength=300, justify="left", fg="#555").pack(anchor="w", padx=10)
        brow = tk.Frame(f); brow.pack(anchor="w", padx=10, pady=6)
        tk.Button(brow, text="\U0001F4CC Pin the window under me",
                  command=self._on_pin_under_cat).pack(side="left")
        tk.Button(brow, text="Unpin all", command=self._on_unpin_all).pack(side="left", padx=8)
        tk.Frame(f, height=1, bg="#ccc").pack(fill="x", padx=10, pady=4)
        self._pin_list = tk.Frame(f)
        self._pin_list.pack(fill="both", expand=True, padx=10, pady=(0, 10))

    def _on_pin_under_cat(self):
        self.cat._pin_under_cat()
        self._refresh_pins()

    def _on_unpin_all(self):
        self.cat.pinset.unpin_all()
        self._refresh_pins()

    def _unpin_one(self, hwnd):
        self.cat.pinset.toggle(hwnd)      # toggling a pinned hwnd unpins it
        self._refresh_pins()

    def _refresh_pins(self):
        if self.win is None:
            return
        for w in self._pin_list.winfo_children():
            w.destroy()
        pinned = sorted(self.cat.pinset.pinned())
        if not pinned:
            tk.Label(self._pin_list, text="(nothing pinned)", fg="#888").pack(anchor="w")
            return
        for hwnd in pinned:
            row = tk.Frame(self._pin_list); row.pack(fill="x", pady=1)
            title = window.window_title(hwnd) or ("window %d" % hwnd)
            if len(title) > 34:
                title = title[:33] + "…"
            tk.Button(row, text="✕", width=2,
                      command=lambda h=hwnd: self._unpin_one(h)).pack(side="right")
            tk.Label(row, text="• " + title, anchor="w").pack(side="left")

    # --- More tab -------------------------------------------------------
    def _build_more_tab(self):
        f = self._add_tab("More")
        self._more_vars = {}
        for key, label in _MORE_TOGGLES:
            var = tk.IntVar(value=1 if self.cat.cfg["pet"].get(key, True) else 0)
            self._more_vars[key] = var
            tk.Checkbutton(f, text=label, variable=var,
                           command=lambda k=key, v=var: self.cat._set_cfg_flag(k, v.get())
                           ).pack(anchor="w", padx=10, pady=2)
