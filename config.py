"""Toybox configuration: load/save config.json with per-key fallback to defaults."""

import copy
import json
import os
import tempfile

DEFAULTS = {
    "hud": {"x": 40, "y": 40, "alpha": 0.85, "locked": False},
    "clipboard": {"max_items": 20, "hotkey": ["ctrl", "shift", "V"]},
    "pet": {"x": None, "y": None, "sensitivity": 1.6, "floor": 0.02,
            "smoothing": 0.4, "idle_fps": 8, "active_fps": 30},
    "startup": {"hud": False, "clipboard": False, "pet": False},
}


def defaults():
    return copy.deepcopy(DEFAULTS)


def _deep_merge(base, override):
    """Overlay override onto a deep copy of base; unknown keys in override are ignored."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key not in result:
            continue  # ignore keys we don't know about
        if isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
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
