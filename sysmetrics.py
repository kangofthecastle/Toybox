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
