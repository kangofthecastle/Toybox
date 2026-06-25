"""Pure per-app foreground-dwell tally. Sample (app, now) snapshots; dwell time
is accrued to whichever app was foreground between consecutive samples."""


class FocusTally:
    def __init__(self):
        self._totals = {}
        self._cur = None
        self._since = None

    def _accrue(self, now):
        if self._cur and self._since is not None:
            self._totals[self._cur] = self._totals.get(self._cur, 0) + max(0, now - self._since)

    def sample(self, app, now):
        self._accrue(now)
        self._cur = app
        self._since = now

    def top(self, n=3, now=None):
        totals = dict(self._totals)
        if now is not None and self._cur and self._since is not None:
            totals[self._cur] = totals.get(self._cur, 0) + max(0, now - self._since)
        return sorted(totals.items(), key=lambda kv: -kv[1])[:n]
