"""Activity-gated break-nudge scheduler. Accumulates only active wall-time
(idle below the away threshold). All time values are injected."""


class NudgeScheduler:
    def __init__(self, interval_s=3000, away_ms=60000):
        self.interval_s = interval_s
        self.away_ms = away_ms
        self._last_now = None
        self._active = 0.0
        self._snooze_until = 0.0

    def update(self, idle_ms, now):
        if self._last_now is None:
            self._last_now = now
            return False
        dt = max(0.0, now - self._last_now)
        self._last_now = now
        if idle_ms < self.away_ms:
            self._active += dt
        if self._active >= self.interval_s and now >= self._snooze_until:
            self._active = 0.0
            return True
        return False

    def snooze(self, now, secs=300):
        self._active = 0.0
        self._snooze_until = now + secs
