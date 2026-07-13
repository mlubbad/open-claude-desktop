"""Global app settings (the Customize page) shared by both app surfaces.

Moved verbatim from aj360_app/aj360_app/core.py so the FastAPI backend and the
Reflex frontend read/write the same on-disk settings.json. Behavior parity is
the contract — do NOT change the logic. Constants come from ocd_core.config:
SETTINGS_FILE / DEFAULT_SETTINGS / EFFORT_LEVELS.
"""
from __future__ import annotations

import contextlib
import json

from . import config, jsonstore

# Enumerated settings and their allowed values. A value outside its enum — a corrupt
# file, a stale client, a hand-edit — must never persist or propagate: it silently
# falls into downstream else-branches (e.g. an unknown permission_mode would be
# treated as "not auto"). get/save clamp every one of these back to its default.
_ENUMS: dict[str, tuple] = {}


def _enums() -> dict[str, tuple]:
    if not _ENUMS:
        _ENUMS.update({
            "effort": tuple(config.EFFORT_LEVELS),
            "theme": config.THEME_CHOICES,
            "search_provider": config.SEARCH_PROVIDERS,
            "code_execution": config.CODE_EXECUTION_MODES,
            "permission_mode": config.PERMISSION_MODE_CHOICES,
            "opik_mode": config.OPIK_MODES,
        })
    return _ENUMS


def _clamp_enums(s: dict) -> dict:
    for key, allowed in _enums().items():
        if s.get(key) not in allowed:
            s[key] = config.DEFAULT_SETTINGS[key]
    return s


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
    return _clamp_enums(s)


def save_settings(values: dict) -> dict:
    s = get_settings()
    values = dict(values)
    if "profile" in values:
        from . import profile
        values["profile"] = profile.sanitize(values.get("profile"))
    s.update({k: v for k, v in values.items() if k in config.DEFAULT_SETTINGS})
    _clamp_enums(s)  # never persist an out-of-enum value from a stale/buggy client
    # Atomic write (temp file + os.replace): a crash mid-write can never truncate
    # settings.json to invalid JSON, which get_settings() would silently reset to
    # defaults — wiping the user's model/provider/keys/automation config.
    with contextlib.suppress(Exception):
        jsonstore.save_json(config.SETTINGS_FILE, s)
    return s
