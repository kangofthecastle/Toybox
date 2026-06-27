"""Reminder parsing (relative/absolute natural-language) and an atomic-write
JSON store. Parsing is a pure function of the injected now_epoch."""
import json
import os
import re
import tempfile
import time


def _parse_delay(low):
    m = re.search(r"\bin\s+(\d+)\s*h(?:ours?)?(?:\s*(\d+)\s*(?:m(?:in)?)?)?\b", low)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2) or 0) * 60
    m = re.search(r"\bin\s+(\d+)\s*m(?:in(?:utes?)?)?\b", low)
    if m:
        return int(m.group(1)) * 60
    m = re.search(r"\bin\s+(\d+)\s*s(?:ec(?:onds?)?)?\b", low)
    if m:
        return int(m.group(1))
    return None


def _parse_clock(low, now_epoch):
    m = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", low)
    if not m:
        return None
    h, mnt, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ap == "pm" and h != 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    lt = list(time.localtime(now_epoch))
    lt[3], lt[4], lt[5] = h, mnt, 0
    try:
        due = time.mktime(time.struct_time(tuple(lt)))
    except (OverflowError, ValueError):
        return None      # e.g. a pre-1970 local time on Windows -> unrepresentable
    if due <= now_epoch:
        due += 86400
    return due


_TIME_PHRASE = re.compile(
    r"\b(in\s+\d+\s*h(?:ours?)?(?:\s*\d+\s*(?:m(?:in)?)?)?"
    r"|in\s+\d+\s*m(?:in(?:utes?)?)?|in\s+\d+\s*s(?:ec(?:onds?)?)?"
    r"|at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b", re.I)


def parse_reminder(text, now_epoch):
    low = text.lower()
    delay = _parse_delay(low)
    due = now_epoch + delay if delay is not None else _parse_clock(low, now_epoch)
    if due is None:
        return None
    msg = re.sub(r"^\s*remind me(?:\s+to)?\s+", "", text, flags=re.I)
    msg = _TIME_PHRASE.sub("", msg).strip(" ,").strip()
    return (msg or "Reminder", int(due))


_UNIT_SECONDS = {"sec": 1, "min": 60, "hours": 3600}


def due_from_fields(mode, amount, unit, hh, mm, now_epoch):
    """Compute a reminder due-epoch from the Settings tab's structured fields. Pure.

    mode="in": now_epoch + amount * unit-seconds (unit in 'sec'|'min'|'hours'); amount >= 0.
    mode="at": today at hh:mm (24h), rolled to tomorrow if already <= now_epoch.
    Returns an int epoch, or None on invalid input."""
    if mode == "in":
        try:
            amount = int(amount)
        except (TypeError, ValueError):
            return None
        if amount < 0 or unit not in _UNIT_SECONDS:
            return None
        return int(now_epoch) + amount * _UNIT_SECONDS[unit]
    if mode == "at":
        try:
            hh, mm = int(hh), int(mm)
        except (TypeError, ValueError):
            return None
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return None
        lt = list(time.localtime(now_epoch))
        lt[3], lt[4], lt[5] = hh, mm, 0
        try:
            due = time.mktime(time.struct_time(tuple(lt)))
        except (OverflowError, ValueError):
            return None
        if due <= now_epoch:
            due += 86400
        return int(due)
    return None


def format_due(due_epoch, now_epoch):
    """Human-friendly fire time, e.g. '4:12pm'. Prefixes 'tomorrow ' for the next
    calendar day and the weekday abbrev for any later day. Pure (localtime of an
    injected epoch)."""
    due = time.localtime(int(due_epoch))
    h = due.tm_hour % 12 or 12
    ap = "am" if due.tm_hour < 12 else "pm"
    clock = "%d:%02d%s" % (h, due.tm_min, ap)
    now = time.localtime(int(now_epoch))
    if (due.tm_year, due.tm_yday) == (now.tm_year, now.tm_yday):
        return clock
    nxt = time.localtime(int(now_epoch) + 86400)
    if (due.tm_year, due.tm_yday) == (nxt.tm_year, nxt.tm_yday):
        return "tomorrow " + clock
    return time.strftime("%a", due) + " " + clock


class Reminders:
    def __init__(self, path):
        self.path = path
        self._items = self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return []
        if not isinstance(data, list):
            return []
        out = []
        for it in data:
            if (isinstance(it, dict) and isinstance(it.get("text"), str)
                    and isinstance(it.get("due"), (int, float))
                    and not isinstance(it.get("due"), bool)):
                out.append({"text": it["text"], "due": int(it["due"])})
        return out

    def _save(self):
        directory = os.path.dirname(self.path) or "."
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self._items, f, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def add(self, text, due_epoch):
        self._items.append({"text": text, "due": int(due_epoch)})
        self._save()

    def pending(self):
        return [dict(i) for i in sorted(self._items, key=lambda i: i["due"])]

    def due(self, now_epoch):
        fired = [i for i in self._items if i["due"] <= now_epoch]
        if fired:
            self._items = [i for i in self._items if i["due"] > now_epoch]
            self._save()
        return [i["text"] for i in sorted(fired, key=lambda i: i["due"])]

    def cancel(self, text):
        before = len(self._items)
        self._items = [i for i in self._items if i["text"] != text]
        if len(self._items) != before:
            self._save()

    def remove(self, text, due):
        """Remove the single pending item matching both text and due epoch."""
        due = int(due)
        for i, it in enumerate(self._items):
            if it["text"] == text and int(it["due"]) == due:
                del self._items[i]
                self._save()
                return
