"""Tracks which windows the cat has pinned always-on-top. The OS toggle is
injected (toggle_fn(hwnd, on)) so the bookkeeping is pure and unit-testable."""


class PinSet:
    def __init__(self, toggle_fn):
        self._toggle = toggle_fn
        self._pinned = set()

    def is_pinned(self, hwnd):
        return hwnd in self._pinned

    def pinned(self):
        return set(self._pinned)

    def toggle(self, hwnd):
        on = hwnd not in self._pinned
        self._toggle(hwnd, on)
        if on:
            self._pinned.add(hwnd)
        else:
            self._pinned.discard(hwnd)
        return on

    def unpin_all(self):
        for hwnd in list(self._pinned):
            self._toggle(hwnd, False)
        self._pinned.clear()
