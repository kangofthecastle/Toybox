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
