"""Pure schedule logic: turn a read_workbook() grid into a Schedule and answer
"what's scheduled at `now`". No I/O, no Tk, no ambient clock -- `now` is injected
so every rule is deterministic and unit-testable. Times are 12-hour with am/pm
resolved by monotonic top-down inference (noon then 1:00 -> 13:00). Never raises;
malformed input yields an empty Schedule (Slot kind 'none')."""
import datetime
import re
from collections import namedtuple

Slot = namedtuple("Slot", ["kind", "start", "end", "task"],
                  defaults=(None, None, None))
# kind: "now" | "next" | "none". start/end are datetime (or None); task trimmed str.

_EPOCH = datetime.date(1899, 12, 30)     # Excel serial-date epoch
_TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?")
_DASH_RE = re.compile(r"\s*(?:–|—|-|to)\s*")   # en-dash / em-dash / hyphen / "to"
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
           "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_PLACEHOLDERS = {"", "-", "–", "—", "--"}


def _is_task(cell):
    """True when a day-cell holds a real task (not a placeholder / blank)."""
    if cell is None:
        return False
    return str(cell).strip() not in _PLACEHOLDERS


def _is_time_header(cell):
    """True when a column-A cell marks the header row (text == 'time')."""
    return cell is not None and str(cell).strip().lower() == "time"


def _parse_time(token):
    """'H[:MM]' (12-hour) -> (hour 1..12, minute) or None."""
    m = _TIME_RE.search(token or "")
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    if not (1 <= hour <= 12) or not (0 <= minute <= 59):
        return None
    return hour, minute


def _split_range(text):
    """Split a range cell on dash/'to' into (left, right) or None."""
    parts = _DASH_RE.split((text or "").strip(), maxsplit=1)
    return (parts[0], parts[1]) if len(parts) == 2 else None


def _to_minutes(hour, minute, running):
    """Resolve a 12-hour (hour, minute) to minutes-since-midnight >= `running`,
    adding 12h until it stops going backwards. This is the am/pm inference:
    12:00 after 11:00 -> 720 (noon); 1:00 after noon -> 780 (13:00)."""
    base = (hour % 12) * 60 + minute
    while base < running:
        base += 720
    return base


class _DayColumn:
    """One dated day-column: a date matcher + its chronological blocks."""
    def __init__(self, month, day, year, weekday):
        self.month = month
        self.day = day
        self.year = year          # known for serial dates; None for text headers
        self.weekday = weekday    # 0..6 or None
        self.blocks = []          # list of (start_min, end_min, task)

    def matches(self, d):
        if self.month != d.month or self.day != d.day:
            return False
        if self.year is not None and self.year != d.year:
            return False
        if self.weekday is not None and self.weekday != d.weekday():
            return False
        return True


def _parse_day_header(cell):
    """A header cell -> _DayColumn matcher, or None. Numeric -> real Excel-serial
    date (year known). Text ('Mon Jun 29') -> month+day (+weekday if present)."""
    if cell is None:
        return None
    if isinstance(cell, (int, float)) and not isinstance(cell, bool):
        try:
            d = _EPOCH + datetime.timedelta(days=int(cell))
        except (OverflowError, ValueError):
            return None
        return _DayColumn(d.month, d.day, d.year, d.weekday())
    text = str(cell).strip().lower()
    if not text:
        return None
    month = day = weekday = None
    for tok in re.split(r"[^a-z0-9]+", text):
        if not tok:
            continue
        if tok[:3] in _WEEKDAYS and weekday is None:
            weekday = _WEEKDAYS[tok[:3]]
        elif tok[:3] in _MONTHS and month is None:
            month = _MONTHS[tok[:3]]
        elif tok.isdigit() and day is None:
            day = int(tok)
    if month is None or day is None or not (1 <= day <= 31):
        return None
    return _DayColumn(month, day, None, weekday)


def _parse_sheet(grid):
    """One grid -> list of _DayColumn (with blocks). [] when no header row or no
    dated columns."""
    if not grid:
        return []
    header_idx = None
    for i, row in enumerate(grid):
        if row and _is_time_header(row[0]):
            header_idx = i
            break
    if header_idx is None:
        return []
    header = grid[header_idx]
    col_map = {}
    for ci in range(1, len(header)):
        dc = _parse_day_header(header[ci])
        if dc is not None:
            col_map[ci] = dc
    if not col_map:
        return []
    running = 0
    for row in grid[header_idx + 1:]:
        if not row or row[0] is None:
            continue
        rng = _split_range(str(row[0]))
        if rng is None:
            continue
        s = _parse_time(rng[0])
        e = _parse_time(rng[1])
        if s is None or e is None:
            continue
        start_min = _to_minutes(s[0], s[1], running)
        running = start_min
        end_min = _to_minutes(e[0], e[1], running)
        running = end_min
        for ci, dc in col_map.items():
            task = row[ci] if ci < len(row) else None
            if _is_task(task):
                dc.blocks.append((start_min, end_min, str(task).strip()))
    return list(col_map.values())


class Schedule:
    """Parsed schedule: all dated columns across all sheets. at(now) is cheap."""
    def __init__(self, columns):
        self._columns = columns

    def at(self, now):
        d = now.date()
        col = next((c for c in self._columns if c.matches(d)), None)
        if col is None:
            return Slot("none")
        midnight = datetime.datetime.combine(d, datetime.time())
        upcoming = None
        for start_min, end_min, task in col.blocks:      # blocks are chronological
            start = midnight + datetime.timedelta(minutes=start_min)
            end = midnight + datetime.timedelta(minutes=end_min)
            if start <= now < end:
                return Slot("now", start, end, task)
            if now < start and upcoming is None:
                upcoming = Slot("next", start, end, task)
        return upcoming or Slot("none")


def parse_schedule(workbook):
    """read_workbook() output -> Schedule. Never raises; non-dict / empty -> an
    empty Schedule (at() returns kind 'none')."""
    if not isinstance(workbook, dict):
        return Schedule([])
    columns = []
    for grid in workbook.values():
        try:
            columns.extend(_parse_sheet(grid))
        except Exception:
            continue      # one malformed sheet must not sink the rest
    return Schedule(columns)
