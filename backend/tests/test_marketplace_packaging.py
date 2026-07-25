"""Packaged-build delivery of the bundled marketplace catalog.

A packaged desktop install starts from an EMPTY per-user data root (the Tauri
shell points the frozen sidecar at it via AJ360_DATA_DIR), so the bundled
catalog cannot live there: it ships INSIDE the frozen backend as PyInstaller
datas (backend/ocd-backend.spec) and ``config.MARKETPLACE_DIR`` resolves into
the extraction dir (``sys._MEIPASS``) when ``sys.frozen`` is set. The catalog
stays immutable; installs COPY out of it into the mutable per-user PLUGINS_DIR
(2026-07-25 review, "packaged marketplace delivery" release blocker).
"""
from __future__ import annotations

import contextlib
import importlib
import re
import shutil
import sys
from pathlib import Path

from ocd_core import integrations, marketplace

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = Path(__file__).resolve().parents[2]
_CATALOG = _REPO / "content" / "marketplace"
_FOUR = {"base64_tool", "color_convert", "roman_numeral", "word_count"}


def _reload_config():
    return importlib.reload(importlib.import_module("ocd_core.config"))


@contextlib.contextmanager
def _frozen_build(monkeypatch, bundle: Path, data_dir: Path):
    """Simulate the packaged sidecar: sys.frozen + sys._MEIPASS (the PyInstaller
    extraction dir) with the per-user data root pointed at ``data_dir`` — exactly
    how the Tauri shell launches the frozen backend (AJ360_DATA_DIR). Restores
    the real dev config module afterwards regardless of outcome."""
    monkeypatch.delenv("MARKETPLACE_DIR", raising=False)
    monkeypatch.setenv("AJ360_DATA_DIR", str(data_dir))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    try:
        yield _reload_config()
    finally:
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        monkeypatch.delenv("AJ360_DATA_DIR", raising=False)
        monkeypatch.delenv("MARKETPLACE_DIR", raising=False)
        _reload_config()


# --------------------------- delivery: the bundle ships the catalog ------------ #

def test_spec_ships_catalog_inside_the_frozen_backend():
    """The PyInstaller recipe bundles content/marketplace as datas at the exact
    in-bundle path config resolves ("content/marketplace" under _MEIPASS). CI
    cannot run PyInstaller in unit tests, so this pins the recipe itself."""
    spec = (_BACKEND / "ocd-backend.spec").read_text(encoding="utf-8")
    assert re.search(r'datas\s*\+=\s*\[[^\]]*"content/marketplace"', spec), (
        "backend/ocd-backend.spec no longer ships content/marketplace as datas "
        'targeting "content/marketplace" — a packaged install would have an '
        "empty marketplace (2026-07-25 release blocker)")


# --------------------------- resolution: frozen vs dev ------------------------- #

def test_frozen_build_resolves_catalog_inside_bundle_not_data_root(monkeypatch, tmp_path):
    with _frozen_build(monkeypatch, tmp_path / "bundle", tmp_path / "appdata") as cfg:
        assert cfg.MARKETPLACE_DIR == tmp_path / "bundle" / "content" / "marketplace"
        # Never under the per-user data root — that starts empty in a fresh install.
        assert not cfg.MARKETPLACE_DIR.is_relative_to(cfg.REPO_ROOT)


def test_dev_resolution_unchanged(monkeypatch):
    """Source checkouts keep the historical default: the repo's content/marketplace."""
    monkeypatch.delenv("MARKETPLACE_DIR", raising=False)
    monkeypatch.delenv("AJ360_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    cfg = _reload_config()
    assert cfg.MARKETPLACE_DIR == cfg.REPO_ROOT / "content" / "marketplace"
    assert cfg.MARKETPLACE_DIR.is_dir()


def test_env_override_still_wins_in_frozen_build(monkeypatch, tmp_path):
    override = tmp_path / "custom_catalog"
    with _frozen_build(monkeypatch, tmp_path / "bundle", tmp_path / "appdata"):
        monkeypatch.setenv("MARKETPLACE_DIR", str(override))
        cfg = _reload_config()
        assert cfg.MARKETPLACE_DIR == override


# --------------------------- installed-package smoke --------------------------- #

def test_packaged_install_smoke(monkeypatch, tmp_path):
    """Full lifecycle of a fresh packaged install: empty app-data dir, catalog
    only inside the bundle → catalog visible with every entry uninstalled →
    install one → it runs → uninstall → catalog intact, bundle never mutated."""
    bundle = tmp_path / "bundle"
    # What a release build bundles: the catalog sources, never stray __pycache__
    # (running the suite once leaves one in the repo checkout; the spec strips it).
    shutil.copytree(_CATALOG, bundle / "content" / "marketplace",
                    ignore=shutil.ignore_patterns("__pycache__"))
    appdata = tmp_path / "appdata"
    appdata.mkdir()
    with _frozen_build(monkeypatch, bundle, appdata) as cfg:
        assert cfg.MARKETPLACE_DIR == bundle / "content" / "marketplace"
        assert list(appdata.iterdir()) == []  # truly a first launch
        monkeypatch.setattr(integrations, "PLUGINS_DIR", appdata / "plugins")
        before = {f.name: f.read_bytes()
                  for f in (bundle / "content" / "marketplace").glob("*.py")}

        cat = marketplace.catalog()
        assert _FOUR <= {c["name"] for c in cat}
        assert all(c["installed"] is False for c in cat)

        assert marketplace.install("word_count")["ok"] is True
        assert (appdata / "plugins" / "word_count.py").is_file()
        assert any(c["name"] == "word_count" and c["installed"]
                   for c in marketplace.catalog())
        out = integrations.run_plugin("word_count", {"text": "hello packaged world"})
        assert "words: 3" in out

        assert marketplace.uninstall("word_count")["ok"] is True
        assert not (appdata / "plugins" / "word_count.py").exists()
        cat_after = marketplace.catalog()
        assert _FOUR <= {c["name"] for c in cat_after}
        assert all(c["installed"] is False for c in cat_after)

        after = {f.name: f.read_bytes()
                 for f in (bundle / "content" / "marketplace").glob("*.py")}
        assert after == before  # immutable catalog: install/uninstall never touch it
