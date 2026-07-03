"""Standalone macOS clipboard-sync agent. Mirrors the Windows clipboard toy's sync
over the same clipkit core, but reads/writes the clipboard via pbpaste/pbcopy and
runs headless (no Tk). Configure by placing {"passphrase": "..."} in
~/.toybox-clipsync.json with the SAME passphrase as the Windows side, then run:
    python3 clipsync_mac.py
Pure Python 3.12 standard library only."""
import hashlib
import json
import os
import subprocess
import sys
import time
import uuid

from clipkit.net import ClipSyncNode

CONFIG_PATH = os.path.expanduser("~/.toybox-clipsync.json")
_POLL_S = 0.3


def read_clipboard():
    try:
        result = subprocess.run(["pbpaste"], capture_output=True, text=True)
        if result.returncode != 0:
            return ""
        return result.stdout
    except OSError:
        return ""


def write_clipboard(text):
    try:
        subprocess.run(["pbcopy"], input=text.encode("utf-8"))
    except OSError:
        pass


def load_passphrase(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        passphrase = data.get("passphrase")
        return passphrase if isinstance(passphrase, str) else ""
    except (OSError, ValueError, AttributeError):
        return ""


def _hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def poll_once(prev_hash, read_fn, node):
    """Read the clipboard; if it changed, publish it. Return the current hash."""
    text = read_fn()
    if not text:
        return prev_hash
    h = _hash(text)
    if h != prev_hash:
        node.local_change(text)
    return h


def main():
    passphrase = load_passphrase(CONFIG_PATH)
    if not passphrase:
        print("clipsync: no passphrase in %s; not syncing." % CONFIG_PATH,
              file=sys.stderr)
        return
    node = ClipSyncNode(passphrase, write_clipboard, uuid.uuid4().hex)
    node.start()
    prev = _hash(read_clipboard())
    try:
        while True:
            node.poll_incoming()
            prev = poll_once(prev, read_clipboard, node)
            time.sleep(_POLL_S)
    except KeyboardInterrupt:
        pass
    finally:
        node.stop()


if __name__ == "__main__":
    main()
