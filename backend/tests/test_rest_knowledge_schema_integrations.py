import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(db, monkeypatch):
    # avoid hitting BigQuery/Chroma: stub schema search
    from ocd_core import schema_catalog
    monkeypatch.setattr(schema_catalog, "search_schema",
                        lambda q, active_project=None, top_k=6: f"results for {q}")
    from backend.app.main import app
    return TestClient(app)


def test_schema_search(client):
    r = client.get("/schema/search", params={"q": "users"})
    assert r.status_code == 200 and "users" in r.json()["result"]


def test_integrations_lists(client):
    assert client.get("/plugins").status_code == 200
    assert client.get("/skills").status_code == 200
    assert client.get("/connectors").status_code == 200
    assert client.get("/mcp-servers").status_code == 200


def test_knowledge_upload_and_list(client):
    client.post("/projects", json={"name": "K"})
    files = {"file": ("note.txt", b"hello knowledge", "text/plain")}
    r = client.post("/projects/k/files", files=files)
    assert r.status_code == 200
    listed = client.get("/projects/k/files").json()
    assert any(f["name"] == "note.txt" for f in listed)
