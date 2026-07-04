"""Toybox configuration: load/save config.json with per-key fallback to defaults."""

import copy
import json
import os
import tempfile

DEFAULTS = {
    "hud": {"x": 40, "y": 40, "alpha": 0.85, "locked": False, "github_token": "",
            "schedule": {"path": ""}},
    "clipboard": {"max_items": 30, "hotkey": ["ctrl", "shift", "V"],
                  "x": None, "y": None, "capture": True, "layout": "columns",
                  "sync": False, "sync_passphrase": "", "persist_recent": True,
                  "pin": False, "keep_open": False},
    "pet": {"x": None, "y": None, "sensitivity": 1.6, "floor": 0.02,
            "smoothing": 0.4, "idle_fps": 8, "active_fps": 30, "zoom": 4,
            "petting": True, "catnap": True, "greeter": True,
            "nap_after_s": 120, "away_after_s": 300,
            "focus_min": 25, "break_min": 5, "reminders": True,
            "nudges": True, "nudge_min": 50,
            "pin": True, "carry": True},
    "startup": {"hud": False, "clipboard": False, "pet": False},
    "feeds": [],
}


def defaults():
    return copy.deepcopy(DEFAULTS)


def _coerce(default, value):
    """Coerce a loaded leaf value to the type of its default; on a type mismatch
    fall back to the default. This lets every toy trust config.load() without
    re-validating leaves (a hand-edited, JSON-valid but wrong-typed value can't
    crash a consumer). A ``None`` default means "nullable number" (e.g. pet x/y)."""
    if isinstance(default, dict):
        return value if isinstance(value, dict) else default
    if default is None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return int(value)
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if isinstance(default, int):  # non-bool int
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            return value
        if isinstance(value, float) and float(value).is_integer():
            return int(value)
        return default
    if isinstance(default, float):
        if isinstance(value, bool):
            return default
        if isinstance(value, (int, float)):
            return float(value)
        return default
    if isinstance(default, str):
        return value if isinstance(value, str) else default
    if isinstance(default, list):
        return value if isinstance(value, list) else default
    return value


def _deep_merge(base, override):
    """Overlay override onto a deep copy of base; unknown keys are ignored and
    each overlaid leaf is type-coerced against its default (see _coerce)."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key not in result:
            continue  # ignore keys we don't know about
        if isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = _coerce(result[key], value)
    return result


def load(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return defaults()
    if not isinstance(data, dict):
        return defaults()
    return _deep_merge(DEFAULTS, data)


def save(path, cfg):
    """Atomically write cfg as JSON to path (temp file + os.replace)."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def update(path, partial):
    """Scoped read-modify-write: load the CURRENT config from disk, overlay only
    the keys present in `partial`, and atomically write the result. Returns the
    merged config.

    Toybox runs the HUD, clipboard, and pet as separate processes that share one
    config.json. A whole-file `save(path, self.cfg)` from any one of them writes
    its (possibly stale) copy of EVERY key, so it silently clobbers keys another
    process owns -- e.g. a HUD drag-save overwriting `feeds`/`github_token` with
    the empty values it loaded at startup. `update` fixes that: each writer
    persists only the keys it owns (the HUD its window geometry, the settings
    window its feeds + token, clipboard/pet their own section), merging over the
    latest on-disk state so the other keys survive untouched."""
    merged = _deep_merge(load(path), partial)
    save(path, merged)
    return merged
