import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(db):
    from app.main import app
    return TestClient(app)


def test_project_crud(client):
    r = client.post("/projects", json={"name": "Alpha"})
    assert r.status_code == 200 and r.json()["id"] == "alpha"
    assert any(p["id"] == "alpha" for p in client.get("/projects").json())
    client.put("/projects/alpha/instructions", json={"content": "do X"})
    assert client.get("/projects/alpha/instructions").json()["content"] == "do X"
    client.put("/projects/alpha/allowlist", json={"tables": ["analytics.events"]})
    assert client.get("/projects/alpha/allowlist").json()["tables"] == ["analytics.events"]
    assert client.delete("/projects/alpha").status_code == 200
    assert client.get("/projects/alpha").status_code == 404


def test_project_create_with_description_and_patch(client):
    r = client.post("/projects", json={"name": "Beta", "description": "a beta project"})
    assert r.status_code == 200 and r.json()["description"] == "a beta project"
    # PATCH edits details + toggles pinned/archived (only sent fields change).
    r = client.patch("/projects/beta", json={"name": "Beta 2", "pinned": True})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "Beta 2" and body["pinned"] is True
    assert body["description"] == "a beta project"  # untouched
    # Archiving hides it from the default list but not from ?archived=true.
    client.patch("/projects/beta", json={"archived": True})
    assert all(p["id"] != "beta" for p in client.get("/projects").json())
    assert any(p["id"] == "beta" for p in client.get("/projects?archived=true").json())
    assert client.patch("/projects/nope", json={"pinned": True}).status_code == 404
