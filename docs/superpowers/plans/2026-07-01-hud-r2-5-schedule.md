# Schedule Tile (Excel-driven "now") Implementation Plan

> For agentic workers: use subagent-driven-development to execute; steps use checkbox syntax.

**Goal:** Add a pinned "what am I doing right now" tile at the top of the HUD's
feed column, driven by a user-maintained `.xlsx` timetable. A pure-stdlib xlsx
reader (`schedkit/xlsx.py`) + a pure schedule model (`schedkit/model.py`) feed a
background mtime-gated poller thread in `hud.pyw`; each draw tick renders the
task scheduled for the current moment (or the next upcoming task during a gap)
above the tab bar. Tile hidden when no path is configured, no column matches
today, or nothing is scheduled.

**Architecture:** Mirror the existing `feedkit`/`winkit` seams. `schedkit.xlsx`
is a defensive zip-of-XML reader that never raises (bad/locked/missing → `{}`).
`schedkit.model` is pure, clock-free logic: `parse_schedule(workbook) -> Schedule`
and `Schedule.at(now) -> Slot`. In `hud.pyw`, a daemon thread stats the file's
mtime every ~30 s and, on change, re-reads + re-parses into `self.schedule`
behind a lock (mirroring `feedkit.manager`'s daemon-thread idiom). Each
`_draw_feeds` tick calls `schedule.at(now)` (cheap) and paints a pinned tile
above the tab bar, reusing the existing `_fit_px` ellipsis and hover-marquee.

**Tech Stack:** Python 3.12 standard library only. `zipfile` +
`xml.etree.ElementTree` (xlsx), `datetime` (serial dates + time math),
`threading` + `os.stat` (mtime poller), `tkinter` canvas (tile render).

## Global Constraints

- Pure Python 3.12 stdlib; no third-party packages.
- Never weaken urllib default TLS; only http/https may reach the browser.
- config.json is gitignored and holds a live GitHub PAT — never echo/log/commit it; every runtime config write goes through config.update(path, {...}) (scoped read-modify-write) so it cannot clobber another toy's keys.
- The HUD must never crash on bad external input: every parser returns a safe default; every ctypes/WinRT/Tk call is guarded (try/except).
- Lightweight: no busy loops; background polling is mtime/interval-gated.
- Test runner — use this EXACT command form in every "run the test" step:
    C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest <dotted.path> -v
  run from the repo root. Bare "python" is broken on this machine.
- Commit trailer, EXACTLY (every commit step ends with this line):
    Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>

---

## Task 1: schedkit package + defensive .xlsx reader

**Files:**
- Create: `schedkit/__init__.py` (empty package marker)
- Create: `schedkit/xlsx.py`
- Test: `tests/test_schedkit_xlsx.py`

**Interfaces:**
- Produces: `schedkit.xlsx.read_workbook(path) -> dict[str, list[list[object]]]`
  — sheet name → dense 2D grid (cells `str`/`float`/`None`); never raises;
  bad/locked/missing/non-xlsx → `{}`.
- Consumes: `zipfile`, `xml.etree.ElementTree` (stdlib only).

- [ ] Step: write the failing test — create `tests/test_schedkit_xlsx.py`:

```python
import os
import tempfile
import unittest
import zipfile

from schedkit.xlsx import read_workbook


_NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
_RNS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _col_letter(i):
    s = ""
    i += 1
    while i:
        i, rem = divmod(i - 1, 26)
        s = chr(65 + rem) + s
    return s


def _xml_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _make_xlsx(path, sheets, use_shared=True):
    """Write a minimal, reader-compatible .xlsx (a zip of XML). `sheets` is a list
    of (name, rows); each row is a list of cell values (str/int/float/None). Only
    the parts read_workbook needs are written (workbook.xml, its rels,
    sharedStrings.xml, worksheets/sheetN.xml)."""
    shared = []
    shared_index = {}

    def sid(text):
        if text not in shared_index:
            shared_index[text] = len(shared)
            shared.append(text)
        return shared_index[text]

    if use_shared:
        for _name, rows in sheets:
            for row in rows:
                for cell in row:
                    if isinstance(cell, str):
                        sid(cell)

    sheet_parts = []
    for _name, rows in sheets:
        row_xml = []
        for ri, row in enumerate(rows):
            cells_xml = []
            for ci, cell in enumerate(row):
                if cell is None:
                    continue
                ref = "%s%d" % (_col_letter(ci), ri + 1)
                if isinstance(cell, str):
                    if use_shared:
                        cells_xml.append('<c r="%s" t="s"><v>%d</v></c>' % (ref, sid(cell)))
                    else:
                        cells_xml.append('<c r="%s" t="inlineStr"><is><t>%s</t></is></c>'
                                         % (ref, _xml_escape(cell)))
                else:
                    cells_xml.append('<c r="%s"><v>%r</v></c>' % (ref, cell))
            row_xml.append('<row r="%d">%s</row>' % (ri + 1, "".join(cells_xml)))
        sheet_parts.append(
            '<?xml version="1.0"?><worksheet %s><sheetData>%s</sheetData></worksheet>'
            % (_NS, "".join(row_xml)))

    sheets_xml = "".join(
        '<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (_xml_escape(name), i + 1, i + 1)
        for i, (name, _rows) in enumerate(sheets))
    workbook_xml = ('<?xml version="1.0"?><workbook %s %s><sheets>%s</sheets></workbook>'
                    % (_NS, _RNS, sheets_xml))
    rels_xml = (
        '<?xml version="1.0"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join('<Relationship Id="rId%d" Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1)
                  for i in range(len(sheets)))
        + "</Relationships>")

    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("xl/workbook.xml", workbook_xml)
        zf.writestr("xl/_rels/workbook.xml.rels", rels_xml)
        if use_shared:
            zf.writestr("xl/sharedStrings.xml",
                        '<?xml version="1.0"?><sst %s>' % _NS
                        + "".join("<si><t>%s</t></si>" % _xml_escape(s) for s in shared)
                        + "</sst>")
        for i, part in enumerate(sheet_parts):
            zf.writestr("xl/worksheets/sheet%d.xml" % (i + 1), part)


class TestReadWorkbook(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def _p(self, name="a.xlsx"):
        return os.path.join(self.dir, name)

    def test_shared_strings_and_numbers(self):
        p = self._p()
        _make_xlsx(p, [("Sheet1", [["Time", "Mon Jun 29"],
                                   ["7:45-8:45", "Math"],
                                   [45838, 3.5]])])
        wb = read_workbook(p)
        self.assertIn("Sheet1", wb)
        grid = wb["Sheet1"]
        self.assertEqual(grid[0][0], "Time")
        self.assertEqual(grid[0][1], "Mon Jun 29")
        self.assertEqual(grid[1][1], "Math")
        self.assertEqual(grid[2][0], 45838.0)   # numeric -> float (Excel serial)
        self.assertEqual(grid[2][1], 3.5)

    def test_inline_strings(self):
        p = self._p()
        _make_xlsx(p, [("S", [["Hello", "World"]])], use_shared=False)
        self.assertEqual(read_workbook(p)["S"][0], ["Hello", "World"])

    def test_sparse_rows_fill_none(self):
        p = self._p()
        _make_xlsx(p, [("S", [["A", None, "C"], [None, "B"]])])
        wb = read_workbook(p)
        self.assertEqual(wb["S"][0], ["A", None, "C"])
        self.assertEqual(wb["S"][1], [None, "B", None])   # padded to widest row

    def test_multi_sheet(self):
        p = self._p()
        _make_xlsx(p, [("First", [["x"]]), ("Second", [["y"]])])
        wb = read_workbook(p)
        self.assertEqual(set(wb), {"First", "Second"})
        self.assertEqual(wb["First"][0][0], "x")
        self.assertEqual(wb["Second"][0][0], "y")

    def test_missing_file_returns_empty(self):
        self.assertEqual(read_workbook(self._p("nope.xlsx")), {})

    def test_garbage_zip_returns_empty(self):
        p = self._p()
        with open(p, "wb") as f:
            f.write(b"not a zip file at all")
        self.assertEqual(read_workbook(p), {})


if __name__ == "__main__":
    unittest.main()
```

- [ ] Step: run it, expect FAIL — module does not exist yet:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_schedkit_xlsx -v
```
Expected: `ModuleNotFoundError: No module named 'schedkit'` (collection error).

- [ ] Step: implement — create `schedkit/__init__.py` (empty file, zero bytes), then create `schedkit/xlsx.py`:

```python
"""Minimal, defensive .xlsx reader (a zip of XML). Reads .xlsx/.xlsm only;
legacy binary .xls is unsupported. Never raises: a bad/locked/missing file
yields {}. Pure Python 3.12 stdlib (zipfile + xml.etree)."""
import zipfile
import xml.etree.ElementTree as ET


def _local(tag):
    """Local tag/attribute name without its XML namespace ({ns}name -> name)."""
    return tag.rsplit("}", 1)[-1]


def _col_index(ref):
    """0-based column index from a cell reference's leading letters
    (A->0, Z->25, AA->26). None if the ref has no leading letters."""
    letters = ""
    for ch in ref:
        if ch.isalpha():
            letters += ch
        else:
            break
    if not letters:
        return None
    idx = 0
    for ch in letters.upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _read_shared_strings(zf):
    """xl/sharedStrings.xml -> list of decoded strings (each <si> is the concat of
    its <t> descendants). [] when the part is absent or unparseable."""
    try:
        data = zf.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return []
    out = []
    for si in root:
        if _local(si.tag) != "si":
            continue
        parts = [node.text for node in si.iter()
                 if _local(node.tag) == "t" and node.text]
        out.append("".join(parts))
    return out


def _normalize_part(target):
    """Relationship Target -> zip part path. Targets in workbook.xml.rels are
    relative to the xl/ directory; an absolute '/xl/...' just drops the slash."""
    if target.startswith("/"):
        return target.lstrip("/")
    return "xl/" + target


def _sheet_paths(zf):
    """[(sheet_name, part_path)] in workbook order, resolving each sheet's r:id
    through the workbook rels. [] on any failure."""
    try:
        wb = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    except (KeyError, ET.ParseError):
        return []
    id_to_target = {}
    for rel in rels:
        if _local(rel.tag) != "Relationship":
            continue
        rid, target = rel.get("Id"), rel.get("Target")
        if rid and target:
            id_to_target[rid] = target
    out = []
    for sheets in wb:
        if _local(sheets.tag) != "sheets":
            continue
        for sheet in sheets:
            if _local(sheet.tag) != "sheet":
                continue
            name = sheet.get("name") or ""
            rid = None
            for attr, val in sheet.attrib.items():
                if _local(attr) == "id":     # r:id
                    rid = val
                    break
            target = id_to_target.get(rid)
            if target is not None:
                out.append((name, _normalize_part(target)))
    return out


def _cell_value(c, shared):
    """Decode one <c> cell: t='s' -> shared string; t='str'/'inlineStr' -> text;
    otherwise numeric -> float. Unresolvable -> None (never raises)."""
    t = c.get("t")
    if t == "inlineStr":
        return "".join(node.text for node in c.iter()
                       if _local(node.tag) == "t" and node.text)
    v = None
    for node in c:
        if _local(node.tag) == "v":
            v = node.text
            break
    if v is None:
        return None
    if t == "s":
        try:
            return shared[int(v)]
        except (ValueError, IndexError):
            return None
    if t == "str":
        return v
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _read_sheet(zf, part, shared):
    """Dense 2D grid for one worksheet part. Sparse cells fill with None by
    column letter; ragged rows pad to the widest row. [] on any failure."""
    try:
        root = ET.fromstring(zf.read(part))
    except (KeyError, ET.ParseError):
        return []
    data = None
    for child in root:
        if _local(child.tag) == "sheetData":
            data = child
            break
    if data is None:
        return []
    rows = []
    width = 0
    for row in data:
        if _local(row.tag) != "row":
            continue
        cells = []
        col = 0
        for c in row:
            if _local(c.tag) != "c":
                continue
            ci = _col_index(c.get("r") or "")
            if ci is None:
                ci = col
            while len(cells) < ci:
                cells.append(None)
            cells.append(_cell_value(c, shared))
            col = ci + 1
        rows.append(cells)
        width = max(width, len(cells))
    for r in rows:
        while len(r) < width:
            r.append(None)
    return rows


def read_workbook(path):
    """Sheet name -> dense 2D grid. Never raises; bad/locked/missing/non-xlsx
    file -> {}."""
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        return {}
    try:
        shared = _read_shared_strings(zf)
        return {name: _read_sheet(zf, part, shared)
                for name, part in _sheet_paths(zf)}
    except Exception:
        return {}
    finally:
        try:
            zf.close()
        except Exception:
            pass
```

- [ ] Step: run it, expect PASS:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_schedkit_xlsx -v
```

- [ ] Step: commit:

```
git add schedkit/__init__.py schedkit/xlsx.py tests/test_schedkit_xlsx.py
git commit -m "schedkit: defensive pure-stdlib .xlsx reader

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: schedule model (parse + at())

**Files:**
- Create: `schedkit/model.py`
- Test: `tests/test_schedkit_model.py`

**Interfaces:**
- Consumes: `schedkit.xlsx.read_workbook(...)` output shape
  (`dict[str, list[list[object]]]`).
- Produces:
  - `schedkit.model.parse_schedule(workbook) -> Schedule` (never raises;
    non-dict / empty → empty `Schedule`).
  - `schedkit.model.Schedule.at(now: datetime) -> Slot`.
  - `schedkit.model.Slot` = `namedtuple("Slot", ["kind", "start", "end", "task"])`,
    `kind ∈ {"now","next","none"}`; `start`/`end` are `datetime` (or `None`);
    `task` is a trimmed `str` (or `None`).

- [ ] Step: write the failing test — create `tests/test_schedkit_model.py`:

```python
import datetime
import unittest

from schedkit.model import parse_schedule


def _sched(rows, sheet="S"):
    return parse_schedule({sheet: rows})


def _find_weekday(month, day, weekday):
    """A real date on the given month/day whose weekday matches (weekday: Mon=0)."""
    for y in range(2020, 2040):
        d = datetime.date(y, month, day)
        if d.weekday() == weekday:
            return d
    raise AssertionError("no matching date")


class TestParseSchedule(unittest.TestCase):
    def test_now_slot_matches_text_column(self):
        sched = _sched([["Time", "Jun 29"], ["9:00-10:00", "Standup"]])
        slot = sched.at(datetime.datetime(2026, 6, 29, 9, 30))
        self.assertEqual(slot.kind, "now")
        self.assertEqual(slot.task, "Standup")
        self.assertEqual(slot.start.hour, 9)
        self.assertEqual(slot.end.hour, 10)

    def test_next_slot_during_gap(self):
        sched = _sched([["Time", "Jun 29"],
                        ["9:00-10:00", "Morning"],
                        ["1:00-2:00", "Afternoon"]])   # 1:00 infers to 13:00
        slot = sched.at(datetime.datetime(2026, 6, 29, 11, 0))
        self.assertEqual(slot.kind, "next")
        self.assertEqual(slot.task, "Afternoon")
        self.assertEqual(slot.start.hour, 13)

    def test_none_after_last_block(self):
        sched = _sched([["Time", "Jun 29"], ["9:00-10:00", "Work"]])
        self.assertEqual(sched.at(datetime.datetime(2026, 6, 29, 20, 0)).kind, "none")

    def test_noon_wrap_infers_pm(self):
        sched = _sched([["Time", "Jun 29"],
                        ["11:00-12:00", "A"],
                        ["12:00-1:00", "B"],
                        ["1:00-3:00", "C"]])
        slot = sched.at(datetime.datetime(2026, 6, 29, 12, 30))
        self.assertEqual(slot.kind, "now")
        self.assertEqual(slot.task, "B")
        self.assertEqual(slot.start.hour, 12)   # noon, not midnight
        self.assertEqual(slot.end.hour, 13)     # 1:00 -> 13:00

    def test_serial_date_column_and_year_disambiguation(self):
        serial = (datetime.date(2026, 6, 29) - datetime.date(1899, 12, 30)).days
        sched = _sched([["Time", serial], ["9:00-10:00", "Work"]])
        self.assertEqual(sched.at(datetime.datetime(2026, 6, 29, 9, 30)).task, "Work")
        # same month/day, different year -> serial carries the year -> no match
        self.assertEqual(sched.at(datetime.datetime(2025, 6, 29, 9, 30)).kind, "none")

    def test_weekday_agreement_required(self):
        mon = _find_weekday(6, 29, 0)             # a year where Jun 29 is Monday
        sched = _sched([["Time", "Mon Jun 29"], ["9:00-10:00", "Work"]])
        self.assertEqual(sched.at(datetime.datetime(mon.year, 6, 29, 9, 30)).kind, "now")
        other = next(datetime.date(y, 6, 29) for y in range(2020, 2040)
                     if datetime.date(y, 6, 29).weekday() != 0)
        self.assertEqual(sched.at(datetime.datetime(other.year, 6, 29, 9, 30)).kind, "none")

    def test_placeholder_task_skipped(self):
        sched = _sched([["Time", "Jun 29"],
                        ["9:00-10:00", "—"],   # em-dash placeholder
                        ["10:00-11:00", "Real"]])
        slot = sched.at(datetime.datetime(2026, 6, 29, 9, 30))
        self.assertEqual(slot.kind, "next")
        self.assertEqual(slot.task, "Real")

    def test_header_below_title_row_detected(self):
        sched = _sched([["My Week"], ["Time", "Jun 29"], ["9:00-10:00", "Work"]])
        self.assertEqual(sched.at(datetime.datetime(2026, 6, 29, 9, 30)).task, "Work")

    def test_no_matching_column_returns_none(self):
        sched = _sched([["Time", "Jun 30"], ["9:00-10:00", "Work"]])
        self.assertEqual(sched.at(datetime.datetime(2026, 6, 29, 9, 30)).kind, "none")

    def test_bad_or_empty_workbook_returns_none_slot(self):
        now = datetime.datetime(2026, 6, 29, 9, 30)
        self.assertEqual(parse_schedule({}).at(now).kind, "none")
        self.assertEqual(parse_schedule(None).at(now).kind, "none")
        self.assertEqual(parse_schedule({"S": []}).at(now).kind, "none")


if __name__ == "__main__":
    unittest.main()
```

- [ ] Step: run it, expect FAIL — `schedkit.model` does not exist:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_schedkit_model -v
```
Expected: `ModuleNotFoundError: No module named 'schedkit.model'`.

- [ ] Step: implement — create `schedkit/model.py`:

```python
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
```

- [ ] Step: run it, expect PASS:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_schedkit_model -v
```

- [ ] Step: commit:

```
git add schedkit/model.py tests/test_schedkit_model.py
git commit -m "schedkit: schedule model with am/pm inference and date matching

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: config default for hud.schedule.path

**Files:**
- Modify: `config.py` (add `hud.schedule` to `DEFAULTS` so the key round-trips
  through `config.load` — `_deep_merge` drops keys absent from `DEFAULTS`).
- Test: `tests/test_config_schedule.py`

**Interfaces:**
- Produces: `config.DEFAULTS["hud"]["schedule"] == {"path": ""}`; a loaded
  `config.json` containing `hud.schedule.path` survives `config.load`.
- Consumes: nothing new.

- [ ] Step: write the failing test — create `tests/test_config_schedule.py`:

```python
import json
import os
import tempfile
import unittest

import config


class TestConfigScheduleDefault(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "config.json")

    def test_default_shape(self):
        self.assertEqual(config.defaults()["hud"]["schedule"], {"path": ""})

    def test_path_roundtrips_through_load(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"hud": {"schedule": {"path": "C:/x/s.xlsx"}}}, f)
        cfg = config.load(self.path)
        self.assertEqual(cfg["hud"]["schedule"]["path"], "C:/x/s.xlsx")

    def test_missing_schedule_fills_default(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"hud": {"x": 5}}, f)
        cfg = config.load(self.path)
        self.assertEqual(cfg["hud"]["schedule"], {"path": ""})


if __name__ == "__main__":
    unittest.main()
```

- [ ] Step: run it, expect FAIL — `hud.schedule` not in `DEFAULTS` yet:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_config_schedule -v
```
Expected: `KeyError: 'schedule'` in `test_default_shape` (and the roundtrip
assertion fails: `config.load` strips the unknown key).

- [ ] Step: implement — in `config.py`, add the `schedule` sub-dict to the HUD
defaults. Replace this exact line:

```python
    "hud": {"x": 40, "y": 40, "alpha": 0.85, "locked": False, "github_token": ""},
```

with:

```python
    "hud": {"x": 40, "y": 40, "alpha": 0.85, "locked": False, "github_token": "",
            "schedule": {"path": ""}},
```

- [ ] Step: run it, expect PASS (and confirm no regression in the existing config
suite):

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_config_schedule -v
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_config -v
```

- [ ] Step: commit:

```
git add config.py tests/test_config_schedule.py
git commit -m "config: add hud.schedule.path default so the key round-trips

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: HUD integration — mtime poller thread + pinned "now" tile

**Files:**
- Modify: `hud.pyw` (imports; schedule state + poller in `__init__`; new
  `_schedule_*` / `_draw_schedule_tile` methods; a `_draw_schedule_tile` call
  inserted above the tab bar in `_draw_feeds`; poller teardown in `close`).
- Test: `tests/test_smoke_hud.py` (new `TestHudScheduleTile` class).

**Interfaces:**
- Consumes: `schedkit.xlsx.read_workbook`, `schedkit.model.parse_schedule`,
  `Schedule.at(now)`, `config` (`cfg["hud"]["schedule"]["path"]`).
- Produces (on `Hud`):
  - `self.schedule: schedkit.model.Schedule` (guarded by `self._sched_lock`).
  - `_schedule_now(self) -> datetime` (test seam; default `datetime.now()`).
  - `_draw_schedule_tile(self, y) -> int` (renders pinned tile above the tab bar;
    returns the new `y`; `kind == "none"` → tile hidden, `y` unchanged).
  - `_reload_schedule_if_changed(self)` (mtime-gated re-read; retains last-good on
    a `{}` read).

**hud.pyw LAYOUT NOTE:** The pinned tile is inserted in `_draw_feeds`
*immediately before* the `y = self._draw_tab_bar(y)` call and *after* the feed-`y`
initialization — described relatively so it still applies after earlier round-2
features shift the header rows. Anchor the edit on the `_draw_tab_bar` call
(untouched by the other features), never on absolute line numbers.

- [ ] Step: write the failing test — append a new class to
`tests/test_smoke_hud.py`, immediately BEFORE the trailing
`if __name__ == "__main__":` block. Insert:

```python
@unittest.skipUnless(os.name == "nt", "Windows only")
class TestHudScheduleTile(_HudTestBase):
    def _sched(self, rows):
        import schedkit.model as schedmodel
        return schedmodel.parse_schedule({"S": rows})

    def _text_y(self, hud, needle):
        for iid in hud._feed_items:
            try:
                if needle in hud.canvas.itemcget(iid, "text"):
                    return hud.canvas.coords(iid)[1]
            except Exception:
                pass
        return None

    def test_now_tile_renders_task(self):
        import datetime
        root, hud = self._make_hud([])
        try:
            hud.schedule = self._sched([["Time", "Jun 29"], ["9:00-10:00", "Standup"]])
            hud._schedule_now = lambda: datetime.datetime(2026, 6, 29, 9, 30)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("Standup"))
            self.assertTrue(hud._feed_has_text("▸"))     # the now glyph
        finally:
            hud.close(); root.destroy()

    def test_next_tile_shows_time_and_arrow(self):
        import datetime
        root, hud = self._make_hud([])
        try:
            hud.schedule = self._sched([["Time", "Jun 29"], ["9:00-10:00", "Standup"]])
            hud._schedule_now = lambda: datetime.datetime(2026, 6, 29, 8, 0)
            hud._draw_feeds(); root.update_idletasks()
            self.assertTrue(hud._feed_has_text("→"))     # arrow for a next slot
            self.assertTrue(hud._feed_has_text("09:00"))
            self.assertTrue(hud._feed_has_text("Standup"))
        finally:
            hud.close(); root.destroy()

    def test_none_hides_tile_but_tabs_present(self):
        import datetime
        root, hud = self._make_hud([])
        try:
            hud.schedule = self._sched([["Time", "Jun 29"], ["9:00-10:00", "Standup"]])
            hud._schedule_now = lambda: datetime.datetime(2026, 6, 29, 23, 0)
            hud._draw_feeds(); root.update_idletasks()
            self.assertFalse(hud._feed_has_text("Standup"))
            self.assertTrue(hud._feed_has_text("Global"))     # tab bar unaffected
        finally:
            hud.close(); root.destroy()

    def test_tile_is_above_tab_bar(self):
        import datetime
        root, hud = self._make_hud([])
        try:
            hud.schedule = self._sched([["Time", "Jun 29"], ["9:00-10:00", "Standup"]])
            hud._schedule_now = lambda: datetime.datetime(2026, 6, 29, 9, 30)
            hud._draw_feeds(); root.update_idletasks()
            sched_y = self._text_y(hud, "Standup")
            tab_y = self._text_y(hud, "Global")
            self.assertIsNotNone(sched_y)
            self.assertIsNotNone(tab_y)
            self.assertLess(sched_y, tab_y)                   # pinned above the tabs
        finally:
            hud.close(); root.destroy()

    def test_empty_schedule_draws_no_tile_no_crash(self):
        root, hud = self._make_hud([])
        try:
            hud._draw_feeds(); root.update_idletasks()         # default empty Schedule
            self.assertTrue(hud._feed_has_text("Global"))
        finally:
            hud.close(); root.destroy()
```

- [ ] Step: run it, expect FAIL — `_schedule_now` / `_draw_schedule_tile` /
`self.schedule` do not exist yet:

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudScheduleTile -v
```
Expected: `AttributeError: 'Hud' object has no attribute 'schedule'` (in
`test_empty_schedule_draws_no_tile_no_crash`) and analogous failures where
`hud._schedule_now`/`_draw_schedule_tile` are referenced.

- [ ] Step: implement — four edits in `hud.pyw`.

Edit 4a (imports). Replace this exact block:

```python
import feedkit.manager as feedmanager
import feedkit.model as feedmodel
```

with:

```python
import feedkit.manager as feedmanager
import feedkit.model as feedmodel
import schedkit.xlsx as schedxlsx
import schedkit.model as schedmodel
import datetime
import threading
```

Edit 4b (schedule state + poller start in `__init__`). Replace this exact line:

```python
        self.manager = feedmanager.FeedManager(cfg.get("feeds", []), token=token)
```

with:

```python
        self.manager = feedmanager.FeedManager(cfg.get("feeds", []), token=token)
        # Schedule tile state. self.schedule starts empty (tile hidden) and is
        # replaced under the lock by the mtime-gated poller thread. Guarded by the
        # smoke check so a smoke launch starts no thread.
        self.schedule = schedmodel.Schedule([])
        self._sched_lock = threading.Lock()
        self._sched_path = self._schedule_path()
        self._sched_mtime = None
        self._sched_stop = threading.Event()
        self._sched_thread = None
        if not _smoke_ms():
            self._start_schedule_poller()
```

Edit 4c (new methods). Insert the following methods immediately BEFORE the
`def _draw_feeds(self):` line (anchor the edit on that method definition):

```python
    def _schedule_path(self):
        """Absolute .xlsx path from config (hud.schedule.path), or "" when unset
        or malformed -> the tile stays hidden."""
        sched = self.cfg["hud"].get("schedule") or {}
        if not isinstance(sched, dict):
            return ""
        path = sched.get("path") or ""
        return path if isinstance(path, str) else ""

    def _schedule_now(self):
        """Injectable clock for the schedule tile (tests override this)."""
        return datetime.datetime.now()

    def _start_schedule_poller(self):
        """Start the daemon mtime poller (no-op without a configured path)."""
        if not self._sched_path:
            return
        self._sched_thread = threading.Thread(
            target=self._schedule_loop, name="schedpoller", daemon=True)
        self._sched_thread.start()

    def _schedule_loop(self):
        """Every ~30s: re-read the file if its mtime changed. Never touches Tk."""
        while not self._sched_stop.is_set():
            try:
                self._reload_schedule_if_changed()
            except Exception:
                pass
            self._sched_stop.wait(30)

    def _reload_schedule_if_changed(self):
        """mtime-gated re-read + re-parse. A missing/locked file or a {} read
        retains the last-good schedule (and retries next poll); only a non-empty
        workbook replaces self.schedule."""
        path = self._sched_path
        if not path:
            return
        try:
            mtime = os.stat(path).st_mtime
        except OSError:
            return
        if mtime == self._sched_mtime:
            return
        workbook = schedxlsx.read_workbook(path)
        if not workbook:
            return
        schedule = schedmodel.parse_schedule(workbook)
        with self._sched_lock:
            self.schedule = schedule
            self._sched_mtime = mtime

    def _draw_schedule_tile(self, y):
        """Pinned "now" tile above the tab bar. kind 'now' -> "▸ task";
        'next' -> "→ HH:MM  task"; 'none' -> hidden (y unchanged). Reuses the
        pixel-fit ellipsis and registers a marquee record for a truncated line.
        Not clickable (no URL)."""
        with self._sched_lock:
            schedule = self.schedule
        slot = schedule.at(self._schedule_now())
        if slot.kind == "none":
            return y
        if slot.kind == "now":
            text = "▸ " + slot.task
        else:
            text = "→ %s  %s" % (slot.start.strftime("%H:%M"), slot.task)
        c = self.canvas
        y += FEED_TITLE_GAP
        row_y = y + FEED_LINE_H // 2
        fitted = self._fit_px(text, PAD)
        tid = c.create_text(PAD, row_y, anchor="w", text=fitted,
                            fill=ACCENT, font=FEED_TITLE_FONT)
        self._feed_items.append(tid)
        if fitted != text:
            self._scroll_lines.append({"item": tid, "full": text, "x_start": PAD,
                                       "y0": row_y - FEED_LINE_H // 2,
                                       "y1": row_y + FEED_LINE_H // 2})
        return y + FEED_LINE_H + FEED_TITLE_GAP

```

Edit 4d (call the tile above the tab bar in `_draw_feeds`). Replace this exact
line (the tab-bar call — the stable anchor; insert the schedule tile just above
it, after the feed-`y` initialization):

```python
        y = self._draw_tab_bar(y)
```

with:

```python
        y = self._draw_schedule_tile(y)   # pinned "now" tile, above the tab bar
        y = self._draw_tab_bar(y)
```

Edit 4e (teardown in `close`). Replace this exact block:

```python
        try:
            self.manager.stop()
        except Exception:
            pass
```

with:

```python
        try:
            self.manager.stop()
        except Exception:
            pass
        if self._sched_thread is not None:
            self._sched_stop.set()
            try:
                self._sched_thread.join(timeout=2)
            except Exception:
                pass
```

- [ ] Step: run it, expect PASS (schedule tile suite, then the full HUD suite for
regressions):

```
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud.TestHudScheduleTile -v
C:/Users/Warren/AppData/Local/Programs/Python/Python312/python.exe -m unittest tests.test_smoke_hud -v
```

- [ ] Step: commit:

```
git add hud.pyw tests/test_smoke_hud.py
git commit -m "hud: pinned schedule 'now' tile with mtime-gated xlsx poller

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```
