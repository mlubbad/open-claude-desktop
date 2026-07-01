import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(db):
    from backend.app.main import app
    return TestClient(app)


def test_conversation_flow(client):
    client.post("/projects", json={"name": "P"})
    conv = client.post("/projects/p/conversations", json={"first_message": "hi there"}).json()
    cid = conv["id"]
    client.put(f"/projects/p/conversations/{cid}",
               json={"messages": [{"role": "user", "content": "x", "kind": "user"}], "title": "T"})
    got = client.get(f"/projects/p/conversations/{cid}").json()
    assert got["title"] == "T" and got["messages"][-1]["content"] == "x"
    client.patch(f"/projects/p/conversations/{cid}", json={"pinned": True})
    assert client.get("/projects/p/conversations").json()[0]["pinned"] is True
    assert client.post(f"/projects/p/conversations/{cid}/move", json={"dst_project_id": "general"}).json()["ok"] is True
    assert client.delete(f"/projects/general/conversations/{cid}").status_code == 200


def test_save_conversation_accepts_tool_message_without_content(client):
    """Regression: a turn using a tool must still be saveable.

    The frontend persists its full rich message list after each turn, including
    tool-kind entries (id/name/icon/status/summary/error, no `content` key) and
    table/sources entries. The route must accept these as-is (the storage column
    is untyped JSON) instead of rejecting them via an over-narrow Message schema.
    """
    client.post("/projects", json={"name": "P"})
    conv = client.post("/projects/p/conversations", json={"first_message": "hi"}).json()
    cid = conv["id"]
    tool_msg = {
        "role": "tool", "kind": "tool", "id": "call_1", "name": "run_sql",
        "icon": "database", "label_running": "Querying BigQuery",
        "label_done": "Queried BigQuery", "input": "SELECT 1", "status": "error",
        "summary": "", "error": "boom",
    }
    resp = client.put(f"/projects/p/conversations/{cid}",
                      json={"messages": [{"role": "user", "content": "x", "kind": "user"},
                                         tool_msg], "title": "T"})
    assert resp.status_code == 200
    got = client.get(f"/projects/p/conversations/{cid}").json()
    assert got["messages"][-1]["name"] == "run_sql"


def test_put_conversation_persists_tools(client):
    client.post("/projects", json={"name": "P"})
    conv = client.post("/projects/p/conversations", json={"first_message": "hi"}).json()
    cid = conv["id"]
    r = client.put(f"/projects/p/conversations/{cid}",
                   json={"messages": [{"role": "user", "content": "x", "kind": "user"}],
                         "title": "T",
                         "tools": {"mcp": ["playwright"], "bigquery": False}})
    assert r.status_code == 200
    got = client.get(f"/projects/p/conversations/{cid}").json()
    assert got["tools"] == {"mcp": ["playwright"], "bigquery": False}
