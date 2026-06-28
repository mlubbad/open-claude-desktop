import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(db):
    from backend.app.main import app
    return TestClient(app)


def test_project_crud(client):
    r = client.post("/projects", json={"name": "Alpha"})
    assert r.status_code == 200 and r.json()["id"] == "alpha"
    assert any(p["id"] == "alpha" for p in client.get("/projects").json())
    client.put("/projects/alpha/instructions", json={"content": "do X"})
    assert client.get("/projects/alpha/instructions").json()["content"] == "do X"
    client.put("/projects/alpha/allowlist", json={"tables": ["aj360.events"]})
    assert client.get("/projects/alpha/allowlist").json()["tables"] == ["aj360.events"]
    assert client.delete("/projects/alpha").status_code == 200
    assert client.get("/projects/alpha").status_code == 404
