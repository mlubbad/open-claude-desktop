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


def test_conversation_search_route(client):
    client.post("/projects", json={"name": "P"})
    client.post("/projects/p/conversations", json={"first_message": "quarterly revenue forecast"})
    r = client.get("/conversations/search", params={"q": "revenue"})
    assert r.status_code == 200
    hits = r.json()
    assert len(hits) == 1 and hits[0]["matched_in"] == "title"
    # No match -> empty list.
    assert client.get("/conversations/search", params={"q": "nonexistent-term"}).json() == []
