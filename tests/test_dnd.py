import struct
import unittest
from winkit.dnd import build_dropfiles


class TestBuildDropfiles(unittest.TestCase):
    def test_header_layout(self):
        blob = build_dropfiles(["C:\\a.txt"])
        # DROPFILES = pFiles(DWORD)=20, pt.x, pt.y, fNC, fWide(=1) -> 5x int32
        p_files, x, y, f_nc, f_wide = struct.unpack("<Iiiii", blob[:20])
        self.assertEqual(p_files, 20)
        self.assertEqual((x, y, f_nc), (0, 0, 0))
        self.assertEqual(f_wide, 1)

    def test_path_list_is_wide_and_double_null_terminated(self):
        blob = build_dropfiles(["C:\\a.txt"])
        tail = blob[20:].decode("utf-16-le")
        self.assertEqual(tail, "C:\\a.txt\x00\x00")

    def test_multiple_paths(self):
        blob = build_dropfiles(["a", "b"])
        tail = blob[20:].decode("utf-16-le")
        self.assertEqual(tail, "a\x00b\x00\x00")

    def test_even_byte_length(self):
        self.assertEqual(len(build_dropfiles(["x"])) % 2, 0)
