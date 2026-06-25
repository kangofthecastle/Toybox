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


class NapState:
    """Idle-driven nap cycle: awake -> napping (idle exceeds threshold) ->
    startled (fresh input while napping) -> awake (after startle_s)."""

    def __init__(self, sleep_after_ms=120000, startle_s=0.8):
        self.sleep_after_ms = sleep_after_ms
        self.startle_s = startle_s
        self.state = "awake"
        self._startle_start = 0.0

    def reset(self):
        """Drop straight back to 'awake' with no startle -- used when the catnap
        ability is toggled, so a stale internal 'napping' can't fire a spurious
        startle hop when the ability is re-enabled."""
        self.state = "awake"
        self._startle_start = 0.0

    def update(self, idle_ms, now):
        if self.state == "awake":
            if idle_ms >= self.sleep_after_ms:
                self.state = "napping"
        elif self.state == "napping":
            if idle_ms < self.sleep_after_ms:   # input arrived -> jolt awake
                self.state = "startled"
                self._startle_start = now
        elif self.state == "startled":
            if now - self._startle_start >= self.startle_s:
                self.state = "awake"
        return self.state
