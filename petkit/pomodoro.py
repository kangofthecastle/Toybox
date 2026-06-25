"""Focus/Pomodoro timer state machine. The clock is injected (monotonic
seconds) so the logic is pure and unit-testable."""


class Pomodoro:
    def __init__(self, focus_s=1500, break_s=300):
        self.focus_s = focus_s
        self.break_s = break_s
        self.state = "idle"
        self._end = 0.0
        self._paused_remaining = 0.0
        self._paused_phase = "idle"

    def start(self, now):
        self.state = "focus"
        self._end = now + self.focus_s

    def pause(self, now):
        if self.state in ("focus", "break"):
            self._paused_remaining = max(0.0, self._end - now)
            self._paused_phase = self.state
            self.state = "paused"

    def resume(self, now):
        if self.state == "paused":
            self.state = self._paused_phase
            self._end = now + self._paused_remaining

    def cancel(self):
        self.state = "idle"

    def update(self, now):
        if self.state == "focus" and now >= self._end:
            self.state = "break"
            self._end = now + self.break_s
            return "focus_done"
        if self.state == "break" and now >= self._end:
            self.state = "idle"
            return "break_done"
        return None

    def remaining(self, now):
        if self.state == "paused":
            return self._paused_remaining
        if self.state in ("focus", "break"):
            return max(0.0, self._end - now)
        return 0
