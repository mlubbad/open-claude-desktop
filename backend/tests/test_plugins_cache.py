"""P1: list_plugins()/run_plugin() run on every agent turn, so plugin modules must
be cached by (path, mtime) instead of re-executed each call. These tests pin that
behavior: a plugin's top-level code runs once across repeated listings, and again
only after the file changes.
"""
import os
import textwrap
from pathlib import Path

from ocd_core import integrations

# Top-level code appends one byte to a sidecar file every time the module executes,
# so the sidecar's length == number of exec_module() calls. The .txt name keeps it
# out of the *.py plugin glob.
PLUGIN_SRC = textwrap.dedent('''\
    from pathlib import Path
    with Path(__file__).with_name("exec_count.txt").open("a", encoding="utf-8") as _fh:
        _fh.write("x")
    NAME = "counter"
    DESCRIPTION = "counts its own executions"
    TOOL = {"type": "function", "function": {"name": "counter",
        "description": "noop", "parameters": {"type": "object", "properties": {}}}}
    def run(args):
        return "ok"
''')


def _exec_count(plugins: Path) -> int:
    f = plugins / "exec_count.txt"
    return len(f.read_text(encoding="utf-8")) if f.exists() else 0


def _setup(tmp_path, monkeypatch) -> Path:
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    (plugins / "counter.py").write_text(PLUGIN_SRC, encoding="utf-8")
    monkeypatch.setattr(integrations, "PLUGINS_DIR", plugins)
    integrations._PLUGIN_CACHE.clear()
    return plugins


def test_plugin_module_executed_once_across_repeated_listings(tmp_path, monkeypatch):
    plugins = _setup(tmp_path, monkeypatch)
    for _ in range(5):
        assert integrations.list_plugins()[0]["name"] == "counter"
    # Also exercise the other per-turn entry points that load modules.
    assert integrations.plugin_tools(["counter"])
    assert integrations.run_plugin("counter", {}) == "ok"
    assert _exec_count(plugins) == 1  # cached: executed exactly once, not per call


def test_plugin_reexecuted_after_file_change(tmp_path, monkeypatch):
    plugins = _setup(tmp_path, monkeypatch)
    integrations.list_plugins()
    assert _exec_count(plugins) == 1
    # Rewrite the file with a later mtime -> cache miss -> re-exec.
    pf = plugins / "counter.py"
    pf.write_text(PLUGIN_SRC, encoding="utf-8")
    future = os.stat(pf).st_mtime + 10
    os.utime(pf, (future, future))
    integrations.list_plugins()
    assert _exec_count(plugins) == 2
