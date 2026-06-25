"""Time-of-day persona: maps the wall clock to a glow hue + greeting tone.
Pure logic (hour injected) so it's unit-testable."""

# name -> (r, g, b, greeting)
_BANDS = {
    "morning": (255, 196, 120, "morning"),    # warm amber
    "day":     (120, 200, 255, "hello"),       # cool daylight blue
    "evening": (255, 140, 110, "evening"),     # sunset coral
    "night":   (150, 120, 255, "late night"),  # violet
}


def band_name(hour):
    if hour < 5 or hour >= 21:
        return "night"
    if hour < 11:
        return "morning"
    if hour < 17:
        return "day"
    return "evening"


def glow_rgb(hour):
    return _BANDS[band_name(hour)][:3]


def greeting(hour):
    return _BANDS[band_name(hour)][3]
