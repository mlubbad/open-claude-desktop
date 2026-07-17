import pytest
from sqlalchemy import inspect
from ocd_core import tenancy


@pytest.fixture
def multi_tenant(monkeypatch):
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")


def test_workspace_scoped_tables_exist(db):
    from ocd_core.db import engine

    tables = set(inspect(engine.get_engine()).get_table_names())
    assert {
        "workspace",
        "workspacemembership",
        "coworktaskrecord",
        "scheduledtaskrecord",
        "integrationrecord",
        "approvalrecord",
    } <= tables


def test_membership_roles_fail_closed(db, multi_tenant):
    from ocd_core import workspace_access

    workspace_access.create_workspace("ws-a", "Workspace A", "alice")
    assert workspace_access.role_for("alice", "ws-a") == "owner"
    assert workspace_access.role_for("mallory", "ws-a") is None
    workspace_access.set_membership("ws-a", "bob", "viewer", actor_user="alice")
    workspace_access.require_role("bob", "viewer", workspace="ws-a")
    with pytest.raises(workspace_access.WorkspaceRoleForbidden):
        workspace_access.require_role("bob", "member", workspace="ws-a")
    with pytest.raises(workspace_access.WorkspaceRoleForbidden):
        workspace_access.set_membership("ws-a", "mallory", "admin", actor_user="bob")


@pytest.mark.parametrize(
    ("kind", "save_name", "load_name"),
    [
        ("cowork", "upsert_cowork", "list_cowork"),
        ("schedule", "upsert_schedule", "list_schedules"),
        ("approval", "upsert_approval", "list_approvals"),
    ],
)
def test_sql_records_are_isolated_between_two_workspaces(
    db, multi_tenant, kind, save_name, load_name
):
    from ocd_core import workspace_store

    save = getattr(workspace_store, save_name)
    load = getattr(workspace_store, load_name)
    with tenancy.use_workspace("ws-a"):
        save({"id": f"{kind}-a", "status": "pending", "title": "A"})
    with tenancy.use_workspace("ws-b"):
        save({"id": f"{kind}-b", "status": "pending", "title": "B"})

    with tenancy.use_workspace("ws-a"):
        assert {item["id"] for item in load()} == {f"{kind}-a"}
    with tenancy.use_workspace("ws-b"):
        assert {item["id"] for item in load()} == {f"{kind}-b"}


def test_integration_ids_can_repeat_without_cross_tenant_leak(db, multi_tenant):
    from ocd_core import workspace_store

    with tenancy.use_workspace("ws-a"):
        workspace_store.save_integrations("mcp", [{"id": "github", "name": "A"}])
    with tenancy.use_workspace("ws-b"):
        workspace_store.save_integrations("mcp", [{"id": "github", "name": "B"}])

    with tenancy.use_workspace("ws-a"):
        assert workspace_store.load_integrations("mcp") == [{"id": "github", "name": "A"}]
    with tenancy.use_workspace("ws-b"):
        assert workspace_store.load_integrations("mcp") == [{"id": "github", "name": "B"}]


def test_scoped_delete_cannot_delete_other_workspace_record(db, multi_tenant):
    from ocd_core import workspace_store

    with tenancy.use_workspace("ws-a"):
        workspace_store.upsert_schedule({"id": "schedule-a", "goal": "A"})
    with tenancy.use_workspace("ws-b"):
        assert workspace_store.delete_schedule("schedule-a") is False
    with tenancy.use_workspace("ws-a"):
        assert workspace_store.delete_schedule("schedule-a") is True
