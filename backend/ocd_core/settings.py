"""Global app settings (the Customize page) shared by both app surfaces.

Moved verbatim from aj360_app/aj360_app/core.py so the FastAPI backend and the
Reflex frontend read/write the same on-disk settings.json. Behavior parity is
the contract — do NOT change the logic. Constants come from ocd_core.config:
SETTINGS_FILE / DEFAULT_SETTINGS / EFFORT_LEVELS.
"""
from __future__ import annotations

import json

from . import config


def get_settings() -> dict:
    s = dict(config.DEFAULT_SETTINGS)
    try:
        if config.SETTINGS_FILE.exists():
            data = json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # Backward-compat: older files stored "reasoning_level".
                if "effort" not in data and "reasoning_level" in data:
                    data["effort"] = data["reasoning_level"]
                s.update({k: v for k, v in data.items() if k in config.DEFAULT_SETTINGS})
    except Exception:
        pass
    if s.get("effort") not in config.EFFORT_LEVELS:
        s["effort"] = "High"
    return s


def save_settings(values: dict) -> dict:
    s = get_settings()
    s.update({k: v for k, v in values.items() if k in config.DEFAULT_SETTINGS})
    try:
        config.SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    except Exception:
        pass
    return s
