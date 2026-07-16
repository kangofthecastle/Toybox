"""zonekit: monitor-partition (FancyZones-lite) logic for the HUD.

Pure logic lives in ``geometry`` (math) and ``tracker`` (drag state machine) —
no Tk, no ctypes — so they are unit-testable. ``overlay`` holds the Tk overlay
windows. Native monitor/window glue lives in winkit.
See docs/superpowers/specs/2026-07-15-hud-monitor-partitions-design.md.
"""
