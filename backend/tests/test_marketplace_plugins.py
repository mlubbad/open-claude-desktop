"""Canonical marketplace catalog plugins: install-state contract + behavior.

The bundled catalog entries (base64_tool, color_convert, roman_numeral,
word_count) live ONLY in content/marketplace/ and must never ship preinstalled
(2026-07-25 review, F-01): a fresh runtime starts with all of them uninstalled,
and they reach PLUGINS_DIR exclusively through marketplace.install().

Behavior tests load each canonical file through the runtime's own loader
(integrations._load_plugin_module), so what is asserted here is exactly what an
installed copy executes.
"""
from pathlib import Path

from ocd_core import config, integrations, marketplace

_CATALOG = Path(__file__).resolve().parents[2] / "content" / "marketplace"
_FOUR = {"base64_tool", "color_convert", "roman_numeral", "word_count"}


def _plugin(name: str):
    mod = integrations._load_plugin_module(_CATALOG / f"{name}.py")
    assert mod is not None, f"catalog plugin {name} failed to load"
    return mod


# ------------------------- F-01: installation boundary ------------------------- #

def test_real_catalog_starts_uninstalled_in_fresh_runtime(tmp_path, monkeypatch):
    """With an empty PLUGINS_DIR, every real bundled entry is installed=False.

    Guards against catalog entries ever shipping as preinstalled live plugins
    again (they were once committed straight into plugins/, which made a source
    checkout preinstall them and let the UI delete source-controlled files).
    """
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    monkeypatch.setattr(config, "MARKETPLACE_DIR", _CATALOG)
    monkeypatch.setattr(integrations, "PLUGINS_DIR", plugins)
    cat = marketplace.catalog()
    names = {c["name"] for c in cat}
    assert _FOUR <= names
    for c in cat:
        if c["name"] in _FOUR:
            assert c["installed"] is False
            assert c["origin"] == "bundled"


def test_catalog_names_absent_from_runtime_before_install(tmp_path, monkeypatch):
    """Before installation, none of the bundled catalog names is a live plugin."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    monkeypatch.setattr(integrations, "PLUGINS_DIR", plugins)
    live = {p["name"] for p in integrations.list_plugins()}
    assert not (_FOUR & live)
