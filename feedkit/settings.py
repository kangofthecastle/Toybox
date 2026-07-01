"""The HUD's Feed Settings window: a titled, movable Toplevel hosting a
ttk.Notebook with Feeds / GitHub tabs. Built on demand and reused as a singleton;
reads/writes the live cfg and calls back into the Hud. GUI glue only -- the
testable logic lives in feedkit.model. Guards after()/refresh against TclError
like petkit.settings."""
import os
import tkinter as tk
from tkinter import ttk

import config
import feedkit.model as model

_TYPES = ("rss", "json", "text", "github", "notifications", "search", "stocks")

_SEARCH_PRESETS = {
    "My open PRs": "is:open is:pr author:@me",
    "Awaiting my review": "is:open is:pr review-requested:@me",
    "Assigned to me": "is:open assignee:@me",
}


class FeedSettingsWindow:
    def __init__(self, hud):
        self.hud = hud
        self.win = None
        self._nb = None
        self._list = None
        self._type_var = None
        self._fields = {}

    # --- lifecycle ------------------------------------------------------
    def open(self, tab=None):
        if self.win is not None:
            try:
                self.win.deiconify(); self.win.lift(); self.win.focus_force()
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
        self.win = tk.Toplevel(self.hud.root)
        self.win.title("HUD · Feeds")
        self.win.resizable(False, False)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        self._nb = ttk.Notebook(self.win)
        self._nb.pack(fill="both", expand=True, padx=8, pady=8)
        self._build_feeds_tab()
        self._build_github_tab()
        self._refresh_list()

    # --- Feeds tab ------------------------------------------------------
    def _build_feeds_tab(self):
        f = tk.Frame(self._nb)
        self._nb.add(f, text="Feeds")
        self._list = tk.Frame(f)
        self._list.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        tk.Frame(f, height=1, bg="#ccc").pack(fill="x", padx=10, pady=4)
        add = tk.Frame(f); add.pack(anchor="w", padx=10, pady=(2, 10))
        self._type_var = tk.StringVar(value="rss")
        tk.Label(add, text="Add").pack(side="left")
        tk.OptionMenu(add, self._type_var, *_TYPES,
                      command=lambda _=None: self._render_fields()).pack(side="left", padx=4)
        self._fields_frame = tk.Frame(f)
        self._fields_frame.pack(anchor="w", padx=10)
        self._status = tk.StringVar(value="")
        tk.Label(f, textvariable=self._status, fg="#c33").pack(anchor="w", padx=10)
        self._render_fields()

    def _render_fields(self):
        for w in self._fields_frame.winfo_children():
            w.destroy()
        self._fields = {}
        ftype = self._type_var.get()
        spec = {
            "rss":  [("title", "Title"), ("url", "URL"), ("items", "Items"), ("interval", "Interval s")],
            "json": [("title", "Title"), ("url", "URL"), ("path", "JSON path"),
                     ("text", "field:text"), ("urlfield", "field:url"),
                     ("items", "Items"), ("interval", "Interval s")],
            "text": [("title", "Title"), ("url", "URL"), ("regex", "Regex (opt)"),
                     ("items", "Items"), ("interval", "Interval s")],
            "github": [("title", "Title"), ("repo", "owner/name"), ("branch", "Branch"),
                       ("interval", "Interval s")],
            "notifications": [("title", "Title"), ("items", "Items"), ("interval", "Interval s")],
            "search": [("title", "Title"), ("query", "Query"),
                       ("items", "Items"), ("interval", "Interval s")],
            "stocks": [("title", "Title"), ("symbols", "Symbols"), ("interval", "Interval s")],
        }[ftype]
        for key, label in spec:
            row = tk.Frame(self._fields_frame); row.pack(anchor="w", pady=1)
            tk.Label(row, text=label, width=10, anchor="w").pack(side="left")
            var = tk.StringVar()
            tk.Entry(row, width=30, textvariable=var).pack(side="left")
            self._fields[key] = var
        if ftype == "github":
            self._show_ci = tk.IntVar(value=1)
            self._show_notif = tk.IntVar(value=1)
            crow = tk.Frame(self._fields_frame); crow.pack(anchor="w", pady=1)
            tk.Checkbutton(crow, text="CI", variable=self._show_ci).pack(side="left")
            tk.Checkbutton(crow, text="Notifications", variable=self._show_notif).pack(side="left")
        if ftype == "search":
            prow = tk.Frame(self._fields_frame); prow.pack(anchor="w", pady=1)
            tk.Label(prow, text="Preset", width=10, anchor="w").pack(side="left")
            self._preset_var = tk.StringVar(value="")
            tk.OptionMenu(prow, self._preset_var, *_SEARCH_PRESETS,
                          command=self._apply_search_preset).pack(side="left")
        if ftype == "stocks":
            rrow = tk.Frame(self._fields_frame); rrow.pack(anchor="w", pady=1)
            tk.Label(rrow, text="Range", width=10, anchor="w").pack(side="left")
            self._range_var = tk.StringVar(value=model.DEFAULT_STOCK_RANGE)
            tk.OptionMenu(rrow, self._range_var, *model.STOCK_RANGE_ORDER).pack(side="left")
        if model.is_news_type(ftype):
            trow = tk.Frame(self._fields_frame); trow.pack(anchor="w", pady=1)
            tk.Label(trow, text="Tab", width=10, anchor="w").pack(side="left")
            self._tab_var = tk.StringVar(value="global")
            tk.OptionMenu(trow, self._tab_var, *[k for k, _ in model.NEWS_TABS]).pack(side="left")
        tk.Button(self._fields_frame, text="Add feed", command=self._on_add).pack(anchor="w", pady=4)

    def _apply_search_preset(self, name):
        """Fill the Query field from a named preset so the GitHub search syntax
        never has to be typed."""
        query = _SEARCH_PRESETS.get(name)
        if query and "query" in self._fields:
            self._fields["query"].set(query)

    def _on_add(self):
        ftype = self._type_var.get()
        g = lambda k: self._fields[k].get().strip()
        raw = {"type": ftype, "title": g("title")}
        if g("interval"):
            raw["interval"] = _as_int(g("interval"))
        if ftype == "github":
            raw["repo"] = g("repo")
            if g("branch"):
                raw["branch"] = g("branch")
            show = []
            if self._show_ci.get():
                show.append("ci")
            if self._show_notif.get():
                show.append("notifications")
            raw["show"] = show
        elif ftype == "notifications":
            if g("items"):
                raw["items"] = _as_int(g("items"))
        elif ftype == "search":
            raw["query"] = g("query")
            if g("items"):
                raw["items"] = _as_int(g("items"))
        elif ftype == "stocks":
            raw["symbols"] = model.parse_symbols(g("symbols"))
            raw["range"] = self._range_var.get()
        else:
            raw["url"] = g("url")
            if g("items"):
                raw["items"] = _as_int(g("items"))
            if ftype == "json":
                raw["path"] = g("path")
                raw["fields"] = {"text": g("text"), "url": g("urlfield") or None}
            elif ftype == "text" and g("regex"):
                raw["regex"] = g("regex")
        if model.is_news_type(ftype):
            raw["tab"] = self._tab_var.get()
        norm = model.normalize_feed(raw)
        if not norm.get("valid"):
            self._status.set(norm.get("error") or "invalid feed")
            return
        self._status.set("")
        self._add_feed_dict(raw)

    def _add_feed_dict(self, raw):
        """Append a raw feed dict, persist, and push to the manager. Also used by
        tests to add a feed without driving the widgets."""
        feeds = list(self.hud.cfg.get("feeds", []))
        feeds.append(raw)
        self.hud.cfg["feeds"] = feeds
        self._persist()
        self._refresh_list()

    def _remove(self, index):
        feeds = list(self.hud.cfg.get("feeds", []))
        if 0 <= index < len(feeds):
            del feeds[index]
            self.hud.cfg["feeds"] = feeds
            self._persist()
            self._refresh_list()

    def _persist(self):
        # The settings window owns feeds + the github token; persist exactly
        # those via a scoped update so saving them can't clobber the HUD's
        # window position or another toy's section of the shared config.
        try:
            config.update(self.hud.CFG_PATH, {
                "feeds": self.hud.cfg.get("feeds", []),
                "hud": {"github_token": self.hud.cfg["hud"].get("github_token", "")},
            })
        except Exception:
            pass
        self.hud.manager.set_token(self.hud._github_token())
        self.hud.manager.set_feeds(self.hud.cfg["feeds"])
        self.hud.feed_state = {}
        try:
            self.hud._draw_feeds()
        except tk.TclError:
            pass

    def _refresh_list(self):
        if self.win is None:
            return
        try:
            for w in self._list.winfo_children():
                w.destroy()
            feeds = self.hud.cfg.get("feeds", [])
            if not feeds:
                tk.Label(self._list, text="(no feeds)", fg="#888").pack(anchor="w")
                return
            for i, feed in enumerate(feeds):
                norm = model.normalize_feed(feed)
                row = tk.Frame(self._list); row.pack(fill="x", pady=1)
                tk.Button(row, text="✕", width=2,
                          command=lambda idx=i: self._remove(idx)).pack(side="right")
                label = "%s  [%s]%s" % (norm.get("title", "feed"), feed.get("type", "?"),
                                        "" if norm.get("valid") else "  !")
                tk.Label(row, text=label, anchor="w").pack(side="left")
        except tk.TclError:
            return

    # --- GitHub tab -----------------------------------------------------
    def _build_github_tab(self):
        f = tk.Frame(self._nb)
        self._nb.add(f, text="GitHub")
        env_set = bool(os.environ.get("TOYBOX_GITHUB_TOKEN"))
        src = "environment (TOYBOX_GITHUB_TOKEN)" if env_set else "this field / config.json"
        tk.Label(f, text="Active token source: " + src, fg="#555").pack(anchor="w", padx=10, pady=(10, 2))
        tk.Label(f, text="Classic PAT · scope: notifications (+ repo for private repos)",
                 fg="#555").pack(anchor="w", padx=10)
        row = tk.Frame(f); row.pack(anchor="w", padx=10, pady=6)
        self._token_var = tk.StringVar(value=self.hud.cfg["hud"].get("github_token", ""))
        tk.Label(row, text="Token").pack(side="left")
        tk.Entry(row, width=30, show="*", textvariable=self._token_var).pack(side="left", padx=4)
        tk.Button(row, text="Save", command=self._on_save_token).pack(side="left")
        tk.Button(row, text="Test", command=self._on_test_token).pack(side="left", padx=4)
        self._token_status = tk.StringVar(value="")
        tk.Label(f, textvariable=self._token_status, fg="#555").pack(anchor="w", padx=10)

    def _on_save_token(self):
        self.hud.cfg["hud"]["github_token"] = self._token_var.get().strip()
        self._persist()

    def _on_test_token(self):
        """One synchronous /notifications request (acceptable for an explicit
        click) reporting OK (N unread) / bad token / rate-limited / offline."""
        import feedkit.fetch as fetch
        import feedkit.parse as parse
        token = self.hud._github_token()
        res = fetch.fetch(model.github_notifications_url(), headers=model.github_headers(token))
        if res.status == "ok":
            try:
                self._token_status.set("OK (%d unread)" % parse.parse_notifications(res.body))
            except Exception:
                self._token_status.set("bad response")
        elif res.status == "not_modified":
            self._token_status.set("OK")
        else:
            self._token_status.set(res.error or "error")


def _as_int(text):
    try:
        return int(text)
    except (TypeError, ValueError):
        return text     # normalize_feed will coerce/reject it
