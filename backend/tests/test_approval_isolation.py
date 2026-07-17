import asyncio

from ocd_core import tenancy


def test_pending_approval_is_persisted_and_workspace_owned(db, monkeypatch):
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    from ocd_core import permissions, workspace_store

    async def exercise():
        with tenancy.use_workspace("ws-a"):
            waiter = asyncio.create_task(
                permissions.registry.wait(
                    "turn-1", "call-1", 5, tool_name="bash", args={"command": "id"}
                )
            )
        await asyncio.sleep(0)

        with tenancy.use_workspace("ws-b"):
            assert permissions.registry.pending("turn-1") == []
            assert permissions.registry.resolve("turn-1", "call-1", True) is False
            assert workspace_store.list_approvals() == []

        with tenancy.use_workspace("ws-a"):
            records = workspace_store.list_approvals()
            assert len(records) == 1 and records[0]["status"] == "pending"
            assert permissions.registry.resolve("turn-1", "call-1", True) is True

        assert await waiter is True
        with tenancy.use_workspace("ws-a"):
            assert workspace_store.list_approvals()[0]["status"] == "approved"

    asyncio.run(exercise())
