"""Pure CPU-percentage math from GetSystemTimes snapshots."""


def cpu_percent(prev, cur):
    """Compute busy CPU % from two (idle, kernel, user) cumulative-tick snapshots.

    Kernel time includes idle time (per GetSystemTimes), so total = kernel + user
    and busy = total - idle. Returns a float clamped to [0, 100].
    """
    idle_d = cur[0] - prev[0]
    total_d = (cur[1] - prev[1]) + (cur[2] - prev[2])
    if total_d <= 0:
        return 0.0
    busy = total_d - idle_d
    return max(0.0, min(100.0, busy / total_d * 100.0))


def gpu_percent(instances):
    """Aggregate Windows GPU Engine utilization into one 0..100 percentage.

    `instances` is an iterable of (instance_name, value) pairs. Each name is a
    PDH "\\GPU Engine(...)" instance carrying an `engtype_<Type>` token; value is
    that instance's Utilization Percentage. Utilizations are summed per engine
    type (there are often several Copy engines) and the busiest engine type wins
    -- approximating Task Manager's GPU%. Returns a float in [0, 100], or None
    when no engtype-bearing instance is present.
    """
    marker = "engtype_"
    totals = {}
    for name, value in instances:
        i = name.rfind(marker)
        if i == -1:
            continue
        engtype = name[i + len(marker):]
        totals[engtype] = totals.get(engtype, 0.0) + value
    if not totals:
        return None
    return max(0.0, min(100.0, max(totals.values())))
