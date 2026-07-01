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
