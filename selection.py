"""Pure helper for shift-click range selection in a list."""


def shift_range(anchor, clicked):
    """Inclusive set of indices between anchor and clicked. If anchor is None,
    just {clicked}."""
    if anchor is None:
        return {clicked}
    lo, hi = (anchor, clicked) if anchor <= clicked else (clicked, anchor)
    return set(range(lo, hi + 1))
