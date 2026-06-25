"""Humanize an elapsed duration into a short badge string."""


def format_ago(elapsed_seconds):
    """Seconds elapsed -> 'just now' / 'Nm' / 'Nh' / 'Nd'. Negative -> 'just now'."""
    s = elapsed_seconds
    if s < 60:
        return "just now"
    if s < 3600:
        return "%dm" % int(s // 60)
    if s < 86400:
        return "%dh" % int(s // 3600)
    return "%dd" % int(s // 86400)
