import pytest
from fastapi.testclient import TestClient
from ocd_core import tenancy


@pytest.fixture
def multi(monkeypatch):
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    monkeypatch.setenv("OCD_ALLOW_DEV_WORKSPACE_HEADER", "1")


@pytest.fixture
def client(db, multi, monkeypatch, tmp_path):
    from app.main import app
    from ocd_core import integrations

    monkeypatch.setattr(integrations, "CONNECTORS_FILE", tmp_path / "connectors.json")
    monkeypatch.setattr(integrations, "MCP_FILE", tmp_path / "mcp.json")

    return TestClient(app)


def test_cowork_list_get_clear_are_tenant_negative(client):
    from ocd_core import cowork

    task = cowork.Task(
        id="task-a", goal="private", title="private", status="done", workspace="ws-a"
    )
    cowork.manager._tasks[task.id] = task
    with tenancy.use_workspace("ws-a"):
        cowork.manager._save()

    b = {"X-OCD-Workspace": "ws-b"}
    assert client.get("/cowork", headers=b).json() == []
    assert client.get("/cowork/task-a", headers=b).status_code == 404
    assert client.post("/cowork/clear", headers=b).json() == {"cleared": 0}
    a = {"X-OCD-Workspace": "ws-a"}
    assert client.get("/cowork/task-a", headers=a).status_code == 200


def test_schedule_list_update_delete_are_tenant_negative(client, monkeypatch, tmp_path):
    from app.routes import scheduler as route
    from ocd_core import scheduler

    svc = scheduler.SchedulerService(
        scheduler.ScheduleStore(tmp_path / "schedules.json"), launch=lambda _: "task"
    )
    monkeypatch.setattr(route.scheduler, "service", svc)
    a = {"X-OCD-Workspace": "ws-a"}
    b = {"X-OCD-Workspace": "ws-b"}
    created = client.post(
        "/schedules",
        json={"goal": "private", "kind": "interval", "every_seconds": 60},
        headers=a,
    ).json()
    sid = created["id"]

    assert client.get("/schedules", headers=b).json() == []
    assert client.post(f"/schedules/{sid}/enabled", json={"enabled": False}, headers=b).status_code == 404
    assert client.delete(f"/schedules/{sid}", headers=b).status_code == 404
    assert client.post(f"/schedules/{sid}/enabled", json={"enabled": False}, headers=a).status_code == 200


def test_connector_list_and_delete_are_tenant_negative(client):
    from ocd_core import integrations

    with tenancy.use_workspace("ws-a"):
        integrations._save_user_connectors(
            [{"id": "private", "name": "Private", "type": "rest", "base_url": "https://example.com"}]
        )
    b = {"X-OCD-Workspace": "ws-b"}
    assert all(item.get("id") != "private" for item in client.get("/connectors", headers=b).json())
    assert client.delete("/connectors/private", headers=b).status_code == 404
    a = {"X-OCD-Workspace": "ws-a"}
    assert any(item.get("id") == "private" for item in client.get("/connectors", headers=a).json())


def test_mcp_list_and_delete_are_tenant_negative(client):
    from ocd_core import integrations

    with tenancy.use_workspace("ws-a"):
        integrations._save_mcp_servers(
            [{"id": "private", "name": "Private", "transport": "http", "url": "https://example.com/mcp"}]
        )
    b = {"X-OCD-Workspace": "ws-b"}
    assert client.get("/mcp-servers", headers=b).json() == []
    assert client.delete("/mcp-servers/private", headers=b).status_code == 404
    a = {"X-OCD-Workspace": "ws-a"}
    assert [item["id"] for item in client.get("/mcp-servers", headers=a).json()] == ["private"]


def test_marketplace_source_list_and_delete_are_tenant_negative(client, monkeypatch, tmp_path):
    from ocd_core import config, marketplace

    monkeypatch.setattr(config, "MARKETPLACE_SOURCES_DIR", tmp_path / "sources")
    monkeypatch.setattr(config, "MARKETPLACE_SOURCES_FILE", tmp_path / "sources.json")
    with tenancy.use_workspace("ws-a"):
        marketplace._save_sources(
            [{"id": "source-a", "name": "A", "url": "https://example.com/a.git"}]
        )
    b = {"X-OCD-Workspace": "ws-b"}
    assert client.get("/marketplace/sources", headers=b).json()["sources"] == []
    assert client.delete("/marketplace/sources/source-a", headers=b).status_code == 404
