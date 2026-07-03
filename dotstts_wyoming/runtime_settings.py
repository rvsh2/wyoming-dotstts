"""Persistence for runtime-adjustable settings (seed, gain_db).

Settings changed through the HTTP management API are written here so they
survive container restarts. Values from this file override the CLI/env
defaults at startup.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path


LOGGER = logging.getLogger("dotstts-wyoming.settings")

_ALLOWED_KEYS = {
    "seed",
    "gain_db",
    "num_steps",
    "trim_silence",
    "default_voice",
    "language",
    "normalize_text",
}


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
    return {key: raw[key] for key in _ALLOWED_KEYS if key in raw}


def save_settings(path: str | Path, settings: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({key: settings[key] for key in _ALLOWED_KEYS if key in settings}, indent=2) + "\n",
        encoding="utf-8",
    )
