"""Plugin marketplace (Phase 5/6 nice-to-have): browse a bundled catalog, install a
plugin into PLUGINS_DIR (where the runtime picks it up as a tool), and uninstall it —
without ever being able to delete a non-catalog (built-in) plugin.
"""
import shutil
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


# --------------------------- repository sources --------------------------- #

def _setup_sources(tmp_path, monkeypatch):
    """Empty bundled catalog + a sources area, with git clone stubbed to copy a fixture."""
    mkt = tmp_path / "marketplace"
    mkt.mkdir()
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    sources = tmp_path / "sources"
    sources.mkdir()
    monkeypatch.setattr(config, "MARKETPLACE_DIR", mkt)
    monkeypatch.setattr(integrations, "PLUGINS_DIR", plugins)
    monkeypatch.setattr(config, "MARKETPLACE_SOURCES_DIR", sources)
    monkeypatch.setattr(config, "MARKETPLACE_SOURCES_FILE", sources / "sources.json")
    monkeypatch.setattr(config, "MARKETPLACE_ALLOW_REMOTE", True)

    # Fixture repo the fake clone populates the destination from.
    repo = tmp_path / "fixture_repo"
    (repo / "plugins").mkdir(parents=True)
    (repo / "plugins" / "remote_tool.py").write_text(
        PLUGIN_SRC.replace("hello_mp", "remote_tool"), encoding="utf-8")
    (repo / "README.md").write_text("# not a plugin", encoding="utf-8")
    (repo / "_private.py").write_text("secret = 1", encoding="utf-8")  # skipped (underscore)

    def fake_clone(url, ref, dest):
        shutil.copytree(repo, dest)
    monkeypatch.setattr(marketplace, "_clone_repo", fake_clone)
    return plugins


def test_add_source_discovers_and_lists(tmp_path, monkeypatch):
    _setup_sources(tmp_path, monkeypatch)
    res = marketplace.add_source("https://example.com/acme/plugins.git")
    assert res["ok"] is True
    assert res["source"]["plugins"] == 1  # only remote_tool.py (README/_private skipped)
    srcs = marketplace.list_sources()
    assert len(srcs) == 1 and srcs[0]["name"] == "plugins"
    # The source plugin now shows in the merged catalog with its origin.
    entry = next(c for c in marketplace.catalog() if c["name"] == "remote_tool")
    assert entry["source_id"] == srcs[0]["id"] and entry["origin"] == "plugins"


def test_add_source_rejects_bad_url(tmp_path, monkeypatch):
    _setup_sources(tmp_path, monkeypatch)
    assert marketplace.add_source("file:///etc/passwd")["ok"] is False
    assert marketplace.add_source("../../etc")["ok"] is False
    assert marketplace.list_sources() == []


def test_install_and_remove_source_plugin(tmp_path, monkeypatch):
    plugins = _setup_sources(tmp_path, monkeypatch)
    src = marketplace.add_source("https://example.com/acme/plugins.git")["source"]
    # Install the synced plugin — it lands in PLUGINS_DIR under a source-namespaced name.
    assert marketplace.install("remote_tool")["ok"] is True
    installed = list(plugins.glob(f"{src['id']}__*.py"))
    assert len(installed) == 1
    assert any(p["name"] == "remote_tool" for p in integrations.list_plugins())
    # Removing the source uninstalls its plugin file and drops it from the catalog.
    assert marketplace.remove_source(src["id"])["ok"] is True
    assert list(plugins.glob(f"{src['id']}__*.py")) == []
    assert not any(c["name"] == "remote_tool" for c in marketplace.catalog())


def test_add_source_no_plugins_is_rejected(tmp_path, monkeypatch):
    _setup_sources(tmp_path, monkeypatch)

    def clone_empty(url, ref, dest):
        dest.mkdir(parents=True)
        (dest / "readme.txt").write_text("nothing here", encoding="utf-8")
    monkeypatch.setattr(marketplace, "_clone_repo", clone_empty)
    res = marketplace.add_source("https://example.com/empty/repo.git")
    assert res["ok"] is False
    assert marketplace.list_sources() == []  # nothing persisted
