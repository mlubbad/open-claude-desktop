"""HITL permission gate: mode logic + registry resolve/timeout."""
import asyncio

from ocd_core import permissions


def test_requires_approval_modes():
    # auto never prompts
    assert permissions.requires_approval("bash", "auto") is False
    assert permissions.requires_approval("bash", None) is False
    # strict prompts for everything, even read-only
    assert permissions.requires_approval("web_search", "strict") is True
    assert permissions.requires_approval("bash", "strict") is True
    # ask prompts for sensitive tools only
    assert permissions.requires_approval("bash", "ask") is True
    assert permissions.requires_approval("code_execution", "ask") is True
    assert permissions.requires_approval("run_sql", "ask") is True
    assert permissions.requires_approval("web_search", "ask") is False
    assert permissions.requires_approval("search_schema", "ask") is False
    # external/unknown tools are sensitive by default
    assert permissions.requires_approval("mcp_github_create_issue", "ask") is True
    assert permissions.requires_approval("rest_myapi", "ask") is True
    assert permissions.requires_approval("some_plugin", "ask") is True


def test_registry_resolve_returns_false_when_nothing_pending():
    reg = permissions.PermissionRegistry()
    assert reg.resolve("no-such-turn", "tc", True) is False


def test_registry_wait_resolves():
    async def scenario():
        reg = permissions.PermissionRegistry()

        async def resolver():
            for _ in range(200):
                if reg.pending("t1"):
                    assert reg.resolve("t1", "tc1", True) is True
                    return
                await asyncio.sleep(0.005)

        task = asyncio.create_task(resolver())
        approved = await reg.wait("t1", "tc1", timeout=2)
        await task
        return approved

    assert asyncio.run(scenario()) is True


def test_registry_wait_times_out_declined():
    async def scenario():
        reg = permissions.PermissionRegistry()
        return await reg.wait("t1", "tc1", timeout=0.05)  # nobody resolves it

    assert asyncio.run(scenario()) is False
