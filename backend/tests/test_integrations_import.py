"""Smoke tests for the integrations module after its move into ocd_core.

These assert that ``ocd_core.integrations`` imports cleanly (no leftover
``aj360_app``/``core`` references) and that its key public surface is present.
We deliberately avoid the network/subprocess-heavy code paths here.
"""


def test_integrations_imports():
    from ocd_core import integrations  # noqa: F401


def test_key_public_functions_exist():
    from ocd_core import integrations

    for name in (
        "agent_tools",
        "run_tool",
        "list_plugins",
        "plugin_tools",
        "list_connectors",
        "web_search",
        "list_mcp_servers",
    ):
        assert hasattr(integrations, name), f"missing public function: {name}"
        assert callable(getattr(integrations, name)), f"not callable: {name}"
