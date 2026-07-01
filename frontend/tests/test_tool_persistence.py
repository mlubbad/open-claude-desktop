"""AppState snapshots and restores the per-conversation tool/capability selection."""
from __future__ import annotations

from ocd_app.state import AppState


def _bare() -> AppState:
    """A bare AppState that bypasses __init__ but has Reflex's dirty-var bookkeeping
    initialized, so plain attribute assignment (used by the two helpers) works."""
    inst = AppState.__new__(AppState)
    object.__setattr__(inst, "dirty_vars", set())
    return inst


def test_current_tools_snapshot_and_apply_roundtrip():
    inst = _bare()  # bare instance; only exercise the two helpers
    inst.enabled_plugins = ["calculator"]
    inst.enabled_connectors = []
    inst.enabled_mcp = ["playwright"]
    inst.web_search_on = True
    inst.research_on = False
    inst.web_fetch_on = False
    inst.code_exec_on = False
    inst.bash_on = False
    inst.text_editor_on = False
    inst.memory_on = True
    inst.active_skill = "hero"
    inst.bigquery_on = True

    snap = AppState._current_tools(inst)
    assert snap["mcp"] == ["playwright"]
    assert snap["bigquery"] is True
    assert snap["skill"] == "hero"

    fresh = _bare()
    AppState._apply_tools(fresh, snap)
    assert fresh.enabled_mcp == ["playwright"]
    assert fresh.bigquery_on is True
    assert fresh.web_search_on is True
    assert fresh.memory_on is True
    assert fresh.active_skill == "hero"
