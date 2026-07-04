"""Plugin marketplace — browse a bundled, vetted catalog and install plugins into the
user's plugins dir (from which the runtime loads them as agent tools).

Only the bundled catalog is installable. Installing arbitrary remote code would be a
code-execution risk, so remote/URL marketplaces are intentionally out of scope here —
`install` only ever copies a vetted catalog file into ``PLUGINS_DIR``, and `uninstall`
only ever removes a file that is itself in the catalog (so the built-in plugins that
ship in ``PLUGINS_DIR`` but are NOT in the catalog can never be deleted through it).
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from . import config, integrations

_META = {
    "name": re.compile(r'^NAME\s*=\s*["\'](.+?)["\']', re.M),
    "description": re.compile(r'^DESCRIPTION\s*=\s*["\'](.+?)["\']', re.M),
    "category": re.compile(r'^CATEGORY\s*=\s*["\'](.+?)["\']', re.M),
}


def _dir() -> Path:
    return Path(config.MARKETPLACE_DIR)


def _meta(text: str, stem: str) -> dict:
    def grab(key: str, default: str) -> str:
        m = _META[key].search(text)
        return m.group(1) if m else default
    return {"name": grab("name", stem), "description": grab("description", ""),
            "category": grab("category", "Utility")}


def _catalog_files() -> list[Path]:
    d = _dir()
    if not d.is_dir():
        return []
    return [f for f in sorted(d.glob("*.py")) if not f.name.startswith("_")]


def catalog() -> list[dict]:
    """The available plugins, each flagged whether it's already installed."""
    installed = {p["name"] for p in integrations.list_plugins()}
    out = []
    for f in _catalog_files():
        try:
            meta = _meta(f.read_text(encoding="utf-8"), f.stem)
        except OSError:
            continue
        meta["filename"] = f.name
        meta["installed"] = meta["name"] in installed
        out.append(meta)
    return out


def _catalog_file(name: str) -> Path | None:
    for f in _catalog_files():
        try:
            if _meta(f.read_text(encoding="utf-8"), f.stem)["name"] == name:
                return f
        except OSError:
            continue
    return None


def install(name: str) -> dict:
    """Copy a catalog plugin into PLUGINS_DIR, then verify it loads as a real plugin."""
    src = _catalog_file(name)
    if src is None:
        return {"ok": False, "name": name, "detail": "not in the marketplace"}
    dest_dir = Path(integrations.PLUGINS_DIR)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dst = dest_dir / src.name
    try:
        shutil.copyfile(src, dst)
    except OSError as e:
        return {"ok": False, "name": name, "detail": f"could not install: {e}"}
    mod = integrations._load_plugin_module(dst)
    if not (mod and hasattr(mod, "TOOL") and hasattr(mod, "run")):
        dst.unlink(missing_ok=True)
        return {"ok": False, "name": name, "detail": "plugin failed to load"}
    return {"ok": True, "name": name, "installed": True}


def uninstall(name: str) -> dict:
    """Remove a previously-installed CATALOG plugin from PLUGINS_DIR (never a built-in)."""
    src = _catalog_file(name)
    if src is None:
        return {"ok": False, "name": name, "detail": "not a marketplace plugin"}
    dest_dir = Path(integrations.PLUGINS_DIR).resolve()
    dst = (dest_dir / src.name).resolve()
    # Defensive path jail: the target must sit directly inside PLUGINS_DIR.
    if dst.parent != dest_dir:
        return {"ok": False, "name": name, "detail": "refused: path outside plugins dir"}
    if dst.exists():
        dst.unlink()
    return {"ok": True, "name": name, "installed": False}
