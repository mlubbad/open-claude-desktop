"""Tiny atomic JSON-registry helpers shared by the on-disk registries.

Four registries (marketplace sources, the imported-skills manifest, user
connectors, and MCP servers) each used to hand-roll the same "read a JSON file,
fall back to a default on any error; write it back" pair — and only one of them
wrote atomically. This centralizes both halves so:

* reads fail soft — any error (missing file, bad JSON, wrong top-level type)
  returns the caller's ``default`` rather than raising; and
* writes are ATOMIC — a temp file plus ``os.replace`` — so a crash or a
  concurrent writer mid-write can never truncate/corrupt a registry (the bug
  the other three copies had). Writes are also best-effort: an OS error while
  saving is swallowed, matching the prior callers' contract.

The ``default`` doubles as a shape guard: pass ``[]`` and a JSON object on disk
is rejected (returns ``[]``); pass ``{}`` and a JSON array is rejected.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def load_json(path: Path, default: Any) -> Any:
    """Read+parse ``path``; return ``default`` on any error or type mismatch."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    if isinstance(default, list) and not isinstance(data, list):
        return default
    if isinstance(default, dict) and not isinstance(data, dict):
        return default
    return data


def save_json(path: Path, data: Any) -> None:
    """Write ``data`` as pretty JSON to ``path`` atomically and best-effort."""
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        pass
