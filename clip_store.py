"""Clipboard store: recent + favorites lists, each optionally disk-persisted.

An entry is {"text": str, "time": float}. A text is unique across both lists.

Favorites persist whenever a favorites_path is given. Recent persists only when
persist_recent is set AND a recent_path is given -- recent is where secrets
(passwords, tokens) pass through, so persisting it is a deliberate opt-in. To
keep the on-disk recent file bounded, persisted entries older than ttl_seconds
are dropped (on each add and via prune_recent()) and the list is capped at
max_recent.
"""
import json
import os
import tempfile

RECENT_TTL_SECONDS = 20 * 24 * 60 * 60   # persisted recent entries expire after 20 days


class ClipStore:
    def __init__(self, max_recent=30, favorites_path=None,
                 recent_path=None, persist_recent=True,
                 ttl_seconds=RECENT_TTL_SECONDS):
        self.max_recent = max_recent
        self.favorites_path = favorites_path
        self.recent_path = recent_path
        self.persist_recent = persist_recent
        self.ttl_seconds = ttl_seconds
        self._favorites = self._load_list(favorites_path) or []   # newest-favorited first
        self._recent = []                                         # newest first
        if persist_recent:
            self._recent = self._load_list(recent_path) or []

    @staticmethod
    def _find(lst, text):
        for i, entry in enumerate(lst):
            if entry["text"] == text:
                return i
        return -1

    def _prune_recent(self, now):
        """Drop entries older than the TTL, then cap to max_recent."""
        cutoff = now - self.ttl_seconds
        self._recent = [e for e in self._recent if e["time"] >= cutoff]
        del self._recent[self.max_recent:]

    def add(self, text, now):
        if not text or not text.strip():
            return False
        if self._find(self._favorites, text) >= 0:
            return False  # already kept as a favorite
        i = self._find(self._recent, text)
        if i >= 0:
            self._recent.pop(i)
        self._recent.insert(0, {"text": text, "time": now})
        self._prune_recent(now)
        self._save_recent()
        return True

    def prune_recent(self, now):
        """Expire stale entries and persist the result. Call once at startup so a
        long-idle session's loaded recent doesn't keep entries past the TTL."""
        self._prune_recent(now)
        self._save_recent()

    def recent(self):
        return [dict(e) for e in self._recent]

    def favorites(self):
        return [dict(e) for e in self._favorites]

    def favorite(self, text):
        i = self._find(self._recent, text)
        if i < 0:
            return
        self._favorites.insert(0, self._recent.pop(i))
        self._save_favorites()
        self._save_recent()

    def unfavorite(self, text):
        i = self._find(self._favorites, text)
        if i < 0:
            return
        self._recent.insert(0, self._favorites.pop(i))
        del self._recent[self.max_recent:]
        self._save_favorites()
        self._save_recent()

    def delete(self, text):
        i = self._find(self._recent, text)
        if i >= 0:
            self._recent.pop(i)
            self._save_recent()
            return
        j = self._find(self._favorites, text)
        if j >= 0:
            self._favorites.pop(j)
            self._save_favorites()

    def delete_many(self, texts):
        targets = set(texts)
        kept = [e for e in self._recent if e["text"] not in targets]
        if len(kept) != len(self._recent):
            self._recent = kept
            self._save_recent()

    def clear_recent(self):
        self._recent = []
        self._save_recent()

    # --- persistence -----------------------------------------------------
    def _save_favorites(self):
        self._save_list(self.favorites_path, self._favorites)

    def _save_recent(self):
        if not self.persist_recent:
            return
        self._save_list(self.recent_path, self._recent)

    @staticmethod
    def _load_list(path):
        """Load a [{"text","time"}] list from path; None on missing/corrupt/None."""
        if not path:
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        if not isinstance(data, list):
            return None
        return [
            {"text": e["text"], "time": e.get("time", 0)}
            for e in data
            if isinstance(e, dict) and isinstance(e.get("text"), str)
        ]

    @staticmethod
    def _save_list(path, lst):
        """Atomically write lst as JSON to path (temp file + os.replace). No-op
        without a path. Best-effort: on any OS error the write is abandoned and
        the temp file removed, so a failed write never leaves a stray file behind
        -- for recent that file would hold plaintext secrets."""
        if not path:
            return
        tmp = None
        try:
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=directory or ".", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(lst, f, indent=2)
            os.replace(tmp, path)
        except OSError:
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
