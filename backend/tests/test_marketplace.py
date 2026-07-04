"""Plugin marketplace (Phase 5/6 nice-to-have): browse a bundled catalog, install a
plugin into PLUGINS_DIR (where the runtime picks it up as a tool), and uninstall it —
without ever being able to delete a non-catalog (built-in) plugin.
"""
import textwrap
from pathlib import Path

from ocd_core import config, integrations, marketplace

# The real bundled catalog dir, resolved from this file (independent of any config
# pollution — another test reloads config with AJ360_DATA_DIR set and doesn't restore it).
_REAL_MARKETPLACE = Path(__file__).resolve().parents[2] / "content" / "marketplace"

PLUGIN_SRC = textwrap.dedent('''\
    NAME = "hello_mp"
    DESCRIPTION = "Say hello."
    CATEGORY = "Demo"
    TOOL = {"type": "function", "function": {"name": "hello_mp",
        "description": "Say hello.", "parameters": {"type": "object", "properties": {}}}}
    def run(args):
        return "hello!"
''')


def _setup(tmp_path, monkeypatch):
    mkt = tmp_path / "marketplace"
    mkt.mkdir()
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (mkt / "hello_mp.py").write_text(PLUGIN_SRC, encoding="utf-8")
    monkeypatch.setattr(config, "MARKETPLACE_DIR", mkt)
    monkeypatch.setattr(integrations, "PLUGINS_DIR", plugins)
    return mkt, plugins


def test_catalog_lists_and_flags_installed(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    cat = marketplace.catalog()
    assert len(cat) == 1
    assert cat[0]["name"] == "hello_mp"
    assert cat[0]["category"] == "Demo"
    assert cat[0]["installed"] is False


def test_install_makes_plugin_live_then_uninstall(tmp_path, monkeypatch):
    _mkt, plugins = _setup(tmp_path, monkeypatch)
    res = marketplace.install("hello_mp")
    assert res["ok"] is True
    assert (plugins / "hello_mp.py").exists()
    # The catalog now flags it installed and the runtime lists + runs it.
    assert marketplace.catalog()[0]["installed"] is True
    assert any(p["name"] == "hello_mp" for p in integrations.list_plugins())
    assert integrations.run_plugin("hello_mp", {}) == "hello!"
    # Uninstall removes the file.
    res = marketplace.uninstall("hello_mp")
    assert res["ok"] is True
    assert not (plugins / "hello_mp.py").exists()


def test_install_unknown_is_rejected(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    res = marketplace.install("does-not-exist")
    assert res["ok"] is False


def test_uninstall_refuses_non_catalog_plugin(tmp_path, monkeypatch):
    """A plugin that ships in PLUGINS_DIR but is NOT in the catalog (a built-in) cannot
    be deleted through the marketplace."""
    _mkt, plugins = _setup(tmp_path, monkeypatch)
    (plugins / "builtin.py").write_text(PLUGIN_SRC.replace("hello_mp", "builtin"),
                                        encoding="utf-8")
    res = marketplace.uninstall("builtin")
    assert res["ok"] is False
    assert (plugins / "builtin.py").exists()  # untouched


def test_bundled_catalog_is_present_and_loads(monkeypatch):
    """The real bundled catalog is non-empty and every entry is a well-formed plugin."""
    monkeypatch.setattr(config, "MARKETPLACE_DIR", _REAL_MARKETPLACE)
    cat = marketplace.catalog()
    names = {c["name"] for c in cat}
    assert {"word_count", "base64_tool", "roman_numeral", "color_convert"} <= names
