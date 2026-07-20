# backend/ocd_core/workspace_registry.py
"""On-disk registry of code workspaces (id -> root path + rules + recents), stored as a
single atomic JSON file. IDs are short hex; roots are absolute. Used by the harness
routes and the agent turn to resolve a workspace_id to a root + its permission rules."""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import config, jsonstore

_STORE = config.REPO_ROOT / "workspaces.json"
_DEFAULT_PROTECTED = [".env", ".env.*", "*.pem", "id_*"]


def _load() -> dict:
    return jsonstore.load_json(_STORE, {"workspaces": []})


def _save(data: dict) -> None:
    jsonstore.save_json(_STORE, data)


def _id_for(root: str) -> str:
    return hashlib.sha1(str(Path(root).resolve()).encode()).hexdigest()[:12]


def register(root: str) -> dict:
    data = _load()
    wid = _id_for(root)
    for w in data["workspaces"]:
        if w["id"] == wid:
            return w
    ws = {"id": wid, "root": str(Path(root).resolve()),
          "rules": {"allow": [], "deny": [], "ask": []},
          "protected": list(_DEFAULT_PROTECTED),
          "last_used": max((w.get("last_used", 0) for w in data["workspaces"]), default=0) + 1}
    data["workspaces"].append(ws)
    _save(data)
    return ws


def get(wid: str) -> dict | None:
    for w in _load()["workspaces"]:
        if w["id"] == wid:
            return w
    return None


def touch(wid: str) -> None:
    data = _load()
    hi = max((w.get("last_used", 0) for w in data["workspaces"]), default=0)
    for w in data["workspaces"]:
        if w["id"] == wid:
            w["last_used"] = hi + 1
    _save(data)


def set_rules(wid: str, rules: dict) -> None:
    data = _load()
    for w in data["workspaces"]:
        if w["id"] == wid:
            w["rules"] = {"allow": rules.get("allow", []), "deny": rules.get("deny", []),
                          "ask": rules.get("ask", [])}
    _save(data)


def list_recents() -> list[dict]:
    return sorted(_load()["workspaces"], key=lambda w: w.get("last_used", 0), reverse=True)
