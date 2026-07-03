"""Persistence for runtime-adjustable settings.

The file stores ONLY the keys a user explicitly changed through the HTTP
management API (deltas), so untouched settings keep following the CLI/env
configuration across restarts. Values are validated on load — the file is
world-editable and a bad value must degrade to a warning, not break startup.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path


LOGGER = logging.getLogger("dotstts-wyoming.settings")


def _is_valid(key: str, value) -> bool:
    if isinstance(value, bool):
        return key in ("trim_silence", "normalize_text")
    if key == "seed":
        return value is None or (isinstance(value, int) and value >= 0)
    if key == "gain_db":
        return isinstance(value, (int, float)) and -60 <= value <= 60
    if key == "num_steps":
        return isinstance(value, int) and 1 <= value <= 64
    if key in ("default_voice", "language"):
        return value is None or isinstance(value, str)
    return False


def load_settings(path: str | Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        LOGGER.warning("Ignoring unreadable settings file %s: %s", path, err)
        return {}
    if not isinstance(raw, dict):
        LOGGER.warning("Ignoring settings file %s: not a JSON object", path)
        return {}

    settings = {}
    for key, value in raw.items():
        if _is_valid(key, value):
            settings[key] = value
        else:
            LOGGER.warning("Ignoring invalid setting in %s: %s=%r", path, key, value)
    return settings


def save_settings(path: str | Path, settings: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({k: v for k, v in settings.items() if _is_valid(k, v)}, indent=2) + "\n"
    # Write-then-rename so a crash mid-write cannot truncate the file.
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(payload, encoding="utf-8")
    os.replace(temp_path, path)
