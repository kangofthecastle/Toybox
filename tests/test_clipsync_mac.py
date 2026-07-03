import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import clipsync_mac


class FakeNode:
    def __init__(self):
        self.changes = []

    def local_change(self, text):
        self.changes.append(text)


class TestClipboardIO(unittest.TestCase):
    def test_read_clipboard_returns_stdout(self):
        fake = mock.Mock(returncode=0, stdout="copied text")
        with mock.patch("clipsync_mac.subprocess.run", return_value=fake) as run:
            self.assertEqual(clipsync_mac.read_clipboard(), "copied text")
        self.assertEqual(run.call_args.args[0][0], "pbpaste")

    def test_read_clipboard_empty_on_failure(self):
        with mock.patch("clipsync_mac.subprocess.run", side_effect=OSError):
            self.assertEqual(clipsync_mac.read_clipboard(), "")

    def test_write_clipboard_pipes_to_pbcopy(self):
        with mock.patch("clipsync_mac.subprocess.run") as run:
            clipsync_mac.write_clipboard("hello mac")
        self.assertEqual(run.call_args.args[0][0], "pbcopy")
        self.assertEqual(run.call_args.kwargs["input"], b"hello mac")

    def test_write_clipboard_survives_failure(self):
        with mock.patch("clipsync_mac.subprocess.run", side_effect=OSError):
            clipsync_mac.write_clipboard("x")     # must not raise


class TestLoadPassphrase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "cfg.json")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_reads_passphrase(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"passphrase": "secret"}, f)
        self.assertEqual(clipsync_mac.load_passphrase(self.path), "secret")

    def test_missing_file_returns_empty(self):
        self.assertEqual(clipsync_mac.load_passphrase(self.path + ".nope"), "")

    def test_malformed_returns_empty(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{ not json")
        self.assertEqual(clipsync_mac.load_passphrase(self.path), "")

    def test_non_string_passphrase_returns_empty(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"passphrase": 123}, f)
        self.assertEqual(clipsync_mac.load_passphrase(self.path), "")


class TestPollOnce(unittest.TestCase):
    def test_change_triggers_local_change(self):
        node = FakeNode()
        h1 = clipsync_mac.poll_once(None, lambda: "first", node)
        self.assertEqual(node.changes, ["first"])
        h2 = clipsync_mac.poll_once(h1, lambda: "first", node)   # unchanged
        self.assertEqual(node.changes, ["first"])                # not re-sent
        clipsync_mac.poll_once(h2, lambda: "second", node)       # changed
        self.assertEqual(node.changes, ["first", "second"])

    def test_empty_clipboard_ignored(self):
        node = FakeNode()
        clipsync_mac.poll_once(None, lambda: "", node)
        self.assertEqual(node.changes, [])
