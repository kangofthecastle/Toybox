"""Audio-envelope beat/onset detector (pure logic, time injected for testability).

Feeds on a stream of audio output peak samples (0..1). It maintains:
  * envelope -- a smoothed peak used to drive the pet's visual size/bounce.
  * avg      -- a fast-adapting running baseline used for onset detection.

A "beat" fires when the current peak rises clearly above the recent baseline
(peak > avg * sensitivity), is above an absolute noise floor, and a refractory
interval has elapsed since the last beat. Steady (sustained) loudness raises the
baseline, so only onsets fire -- not every tick.
"""


class BeatDetector:
    def __init__(self, sensitivity=1.6, floor=0.02, smoothing=0.4,
                 avg_alpha=0.25, refractory=0.15):
        self.sensitivity = sensitivity
        self.floor = floor
        self.smoothing = smoothing      # envelope EMA factor (higher = snappier)
        self.avg_alpha = avg_alpha      # baseline EMA factor (higher = adapts faster)
        self.refractory = refractory    # min seconds between beats
        self.avg = 0.0
        self.envelope = 0.0
        self.last_beat = None

    def update(self, peak, now):
        if peak < 0.0:
            peak = 0.0
        elif peak > 1.0:
            peak = 1.0

        # Visual envelope: simple EMA toward the current peak.
        self.envelope += self.smoothing * (peak - self.envelope)

        # Onset detection against the PRIOR baseline.
        beat = False
        if peak > self.floor and peak > self.avg * self.sensitivity:
            if self.last_beat is None or (now - self.last_beat) >= self.refractory:
                beat = True
                self.last_beat = now

        # Update baseline AFTER detection so a transient stands out from history.
        self.avg += self.avg_alpha * (peak - self.avg)

        return {"beat": beat, "envelope": self.envelope, "avg": self.avg}
