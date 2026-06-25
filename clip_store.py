"""Clipboard store: recent (in-memory) + favorites (disk-persisted) lists.

An entry is {"text": str, "time": float}. A text is unique across both lists.
Only favorites are written to disk (privacy: in-memory recent never persists).
"""
import json
import os
import tempfile


class ClipStore:
    def __init__(self, max_recent=30, favorites_path=None):
        self.max_recent = max_recent
        self.favorites_path = favorites_path
        self._recent = []      # newest first
        self._favorites = []   # newest-favorited first
        self._load_favorites()

    @staticmethod
    def _find(lst, text):
        for i, entry in enumerate(lst):
            if entry["text"] == text:
                return i
        return -1

    def add(self, text, now):
        if not text or not text.strip():
            return False
        if self._find(self._favorites, text) >= 0:
            return False  # already kept as a favorite
        i = self._find(self._recent, text)
        if i >= 0:
            self._recent.pop(i)
        self._recent.insert(0, {"text": text, "time": now})
        del self._recent[self.max_recent:]
        return True

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

    def unfavorite(self, text):
        i = self._find(self._favorites, text)
        if i < 0:
            return
        self._recent.insert(0, self._favorites.pop(i))
        del self._recent[self.max_recent:]
        self._save_favorites()

    def delete(self, text):
        i = self._find(self._recent, text)
        if i >= 0:
            self._recent.pop(i)
            return
        j = self._find(self._favorites, text)
        if j >= 0:
            self._favorites.pop(j)
            self._save_favorites()

    def delete_many(self, texts):
        targets = set(texts)
        self._recent = [e for e in self._recent if e["text"] not in targets]

    def clear_recent(self):
        self._recent = []

    # --- persistence -----------------------------------------------------
    def _load_favorites(self):
        if not self.favorites_path:
            return
        try:
            with open(self.favorites_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        if isinstance(data, list):
            self._favorites = [
                {"text": e["text"], "time": e.get("time", 0)}
                for e in data
                if isinstance(e, dict) and isinstance(e.get("text"), str)
            ]

    def _save_favorites(self):
        if not self.favorites_path:
            return
        try:
            directory = os.path.dirname(self.favorites_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=directory or ".", suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._favorites, f, indent=2)
            os.replace(tmp, self.favorites_path)
        except OSError:
            pass
