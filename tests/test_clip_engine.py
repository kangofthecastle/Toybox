import unittest

from clipkit.engine import Engine


class Recorder:
    """Fake collaborators: seal tags the text, open untags it, send/apply record."""
    def __init__(self):
        self.sent = []
        self.applied = []

    def seal(self, text):
        return b"F:" + text.encode("utf-8")

    def open(self, frame):
        if not frame.startswith(b"F:"):
            return None
        return frame[2:].decode("utf-8")

    def send(self, frame):
        self.sent.append(frame)

    def apply(self, text):
        self.applied.append(text)

    def engine(self, max_bytes=1_000_000):
        return Engine(self.seal, self.open, self.send, self.apply, max_bytes)


class TestEngine(unittest.TestCase):
    def test_local_change_sends_sealed_frame(self):
        r = Recorder(); e = r.engine()
        e.on_local_change("hello")
        self.assertEqual(r.sent, [b"F:hello"])

    def test_remote_frame_applies_once(self):
        r = Recorder(); e = r.engine()
        e.on_remote_frame(b"F:world")
        self.assertEqual(r.applied, ["world"])

    def test_applied_value_is_not_rebroadcast(self):
        # Remote value arrives and is applied; the ensuing local-change echo of
        # that same value must NOT be sent back (loop guard).
        r = Recorder(); e = r.engine()
        e.on_remote_frame(b"F:shared")
        e.on_local_change("shared")
        self.assertEqual(r.sent, [])

    def test_sent_value_is_not_reapplied(self):
        # We publish a value; a remote frame carrying that same value (our own
        # echo bouncing back) must NOT be applied.
        r = Recorder(); e = r.engine()
        e.on_local_change("mine")
        e.on_remote_frame(b"F:mine")
        self.assertEqual(r.applied, [])

    def test_duplicate_local_change_not_resent(self):
        r = Recorder(); e = r.engine()
        e.on_local_change("dup")
        e.on_local_change("dup")
        self.assertEqual(r.sent, [b"F:dup"])

    def test_new_value_after_duplicate_is_sent(self):
        r = Recorder(); e = r.engine()
        e.on_local_change("a")
        e.on_local_change("a")
        e.on_local_change("b")
        self.assertEqual(r.sent, [b"F:a", b"F:b"])

    def test_returning_to_previous_value_is_resent(self):
        # palindrome a->b->a: after the value moves on, going back to "a" is a
        # genuine change again (the guard only remembers the LAST value).
        r = Recorder(); e = r.engine()
        e.on_local_change("a")
        e.on_local_change("b")
        e.on_local_change("a")
        self.assertEqual(r.sent, [b"F:a", b"F:b", b"F:a"])

    def test_oversized_value_skipped(self):
        r = Recorder(); e = r.engine(max_bytes=8)
        e.on_local_change("x" * 9)
        self.assertEqual(r.sent, [])

    def test_empty_local_change_ignored(self):
        r = Recorder(); e = r.engine()
        e.on_local_change("")
        self.assertEqual(r.sent, [])

    def test_bad_frame_ignored(self):
        r = Recorder(); e = r.engine()
        e.on_remote_frame(b"garbage")           # open() returns None
        self.assertEqual(r.applied, [])

    def test_empty_remote_text_ignored(self):
        r = Recorder(); e = r.engine()
        e.on_remote_frame(b"F:")                 # opens to ""
        self.assertEqual(r.applied, [])
