import struct
import unittest

import appicon


class TestAppIcon(unittest.TestCase):
    def test_render_rgba_size(self):
        rgba = appicon._render_rgba()
        self.assertEqual(len(rgba), appicon.SIZE * appicon.SIZE * 4)

    def test_ico_header_and_entry(self):
        data = appicon.build_ico_bytes()
        self.assertGreater(len(data), 100)
        reserved, typ, count = struct.unpack("<HHH", data[:6])
        self.assertEqual(reserved, 0)
        self.assertEqual(typ, 1)   # 1 = icon
        self.assertEqual(count, 1)
        w, h, colors, res, planes, bpp, size, offset = struct.unpack("<BBBBHHII", data[6:22])
        self.assertEqual(w, appicon.SIZE)
        self.assertEqual(h, appicon.SIZE)
        self.assertEqual(bpp, 32)
        self.assertEqual(offset, 22)
        self.assertEqual(len(data), offset + size)  # entry points at the whole image


if __name__ == "__main__":
    unittest.main()
