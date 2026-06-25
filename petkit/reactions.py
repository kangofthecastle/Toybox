"""Pure pet-reaction logic: petting detection and the nap/box state machine.
All clock and idle values are injected so this is deterministic and testable."""


class PettingDetector:
    """Counts horizontal cursor direction-reversals while the cursor is over the
    cat; enough reversals within a sliding time window reads as 'petting'."""

    def __init__(self, reversals_needed=3, window_s=1.2):
        self.reversals_needed = reversals_needed
        self.window_s = window_s
        self._last_x = None
        self._last_dir = 0
        self._reversals = []  # monotonic timestamps of recent reversals

    def _prune(self, now):
        cutoff = now - self.window_s
        self._reversals = [t for t in self._reversals if t >= cutoff]

    def update(self, x, inside, now):
        if not inside:
            self._last_x = None
            self._last_dir = 0
            return self.active(now)
        if self._last_x is not None:
            dx = x - self._last_x
            if dx != 0:
                d = 1 if dx > 0 else -1
                if self._last_dir != 0 and d != self._last_dir:
                    self._reversals.append(now)
                self._last_dir = d
        self._last_x = x
        return self.active(now)

    def active(self, now):
        self._prune(now)
        return len(self._reversals) >= self.reversals_needed
