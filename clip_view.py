"""Pure view-logic for the clipboard panel (no Tk; unit-tested).

Kept separate from clipboard.pyw because that module runs side effects at
import (path insertion, stream guarding) and pulls in Tk + winkit, so its
helpers cannot be unit-tested directly. Mirrors clip_store.py / clip_history.py.
"""

_COLUMNS = "columns"
_STACKED = "stacked"
_SIZES = {_COLUMNS: (632, 420), _STACKED: (380, 640)}


def flatten_line(text):
    """Collapse text to one display line (no length cap).

    CRLF and CR become a space; LF becomes a ' ⏎ ' marker; tabs become spaces;
    the result is stripped. An empty result returns the '⏎' glyph.
    """
    flat = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ⏎ ")
    flat = flat.replace("\t", " ").strip()
    return flat or "⏎"


def normalize_layout(layout):
    """Return layout if it is a known value, else 'columns'."""
    return layout if layout in (_COLUMNS, _STACKED) else _COLUMNS


def next_layout(layout):
    """The other layout; an unknown value toggles to 'stacked'."""
    return _COLUMNS if layout == _STACKED else _STACKED


def panel_size(layout):
    """(width, height) for the panel Toplevel; unknown -> columns size."""
    return _SIZES.get(layout, _SIZES[_COLUMNS])
