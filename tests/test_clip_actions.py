import unittest
from petkit.clip_actions import analyze, safe_eval


class TestSafeEval(unittest.TestCase):
    def test_arithmetic(self):
        self.assertEqual(safe_eval("2+3*4"), 14)
        self.assertEqual(safe_eval("(1+2)/3"), 1.0)
        self.assertEqual(safe_eval("2**10"), 1024)

    def test_rejects_names_and_calls(self):
        self.assertIsNone(safe_eval("__import__('os')"))
        self.assertIsNone(safe_eval("open('x')"))
        self.assertIsNone(safe_eval("a+1"))

    def test_rejects_div_by_zero_and_garbage(self):
        self.assertIsNone(safe_eval("1/0"))
        self.assertIsNone(safe_eval("not an expression"))


class TestAnalyze(unittest.TestCase):
    def test_math(self):
        self.assertEqual(analyze("2 + 2"), {"kind": "math", "result": "4"})

    def test_url(self):
        self.assertEqual(analyze("https://example.com/x"),
                         {"kind": "url", "url": "https://example.com/x"})

    def test_hex_color(self):
        self.assertEqual(analyze("#ff8800"), {"kind": "color", "hex": "#ff8800"})
        self.assertEqual(analyze("aabbcc"), {"kind": "color", "hex": "#aabbcc"})

    def test_plain_text_is_none(self):
        self.assertIsNone(analyze("hello world"))

    def test_blank_is_none(self):
        self.assertIsNone(analyze("   "))
