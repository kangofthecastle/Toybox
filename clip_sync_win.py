"""Windows glue connecting the clipboard toy to the clipkit sync node. Kept as a
separate importable module (not inline in clipboard.pyw) so the wiring is
unit-testable with fakes, no Tk required."""
import time
import uuid

from clipkit import net
from clipkit.net import ClipSyncNode


def sync_enabled(cfg):
    c = cfg.get("clipboard", {})
    return bool(c.get("sync")) and bool(c.get("sync_passphrase"))


def make_apply(set_clipboard, store, absorb, now=time.time):
    """Return apply_fn(text): set the local clipboard to a peer's text WITHOUT
    re-broadcasting it. set_clipboard(text) writes the OS clipboard; absorb()
    advances the toy's clipboard-sequence baseline so its poll loop swallows this
    write (no echo); store.add records it in history like any copy."""
    def apply(text):
        set_clipboard(text)
        absorb()
        try:
            store.add(text, now())
        except Exception:
            pass
    return apply


def build_node(cfg, apply_fn, instance_id=None,
               udp_port=net.UDP_PORT, tcp_port=net.TCP_PORT):
    """Build (but do not start) a ClipSyncNode from config, or None if sync off."""
    if not sync_enabled(cfg):
        return None
    return ClipSyncNode(cfg["clipboard"]["sync_passphrase"], apply_fn,
                        instance_id or uuid.uuid4().hex,
                        udp_port=udp_port, tcp_port=tcp_port)
