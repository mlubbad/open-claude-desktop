"""Plugin dispatch resolves by NAME, independent of the internal importlib
module-id prefix. Locks in that renaming that prefix cannot break dispatch."""
from ocd_core import integrations


def test_calculator_plugin_dispatches():
    out = integrations.run_tool("calculator", {"expression": "2*(3+4)"})
    assert out == "2*(3+4) = 14"


def test_plugin_module_id_is_not_branded():
    # The internal importlib module id must not carry AJ360 branding.
    import inspect
    src = inspect.getsource(integrations._load_plugin_module)
    assert "aj360_plugin_" not in src
    assert "plugin_" in src
