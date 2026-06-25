"""Welcome-back greeter: fires once when activity resumes after an away period.
Idle values are injected so the logic is pure and unit-testable."""


class Greeter:
    def __init__(self, away_after_ms=300000):
        self.away_after_ms = away_after_ms
        self._was_away = False
        self._peak_idle = 0

    def update(self, idle_ms):
        if idle_ms >= self.away_after_ms:
            self._was_away = True
            self._peak_idle = max(self._peak_idle, idle_ms)
            return None
        if self._was_away:
            self._was_away = False
            minutes = self._peak_idle // 60000
            self._peak_idle = 0
            if minutes >= 1:
                return "Welcome back! (%d min)" % minutes
            return "Welcome back!"
        return None
