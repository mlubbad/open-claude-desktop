import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(db):
    from backend.app.main import app
    return TestClient(app)


def test_settings_get_put(client):
    base = client.get("/settings").json()
    assert "model" in base and "effort" in base
    client.put("/settings", json={"effort": "Low"})
    assert client.get("/settings").json()["effort"] == "Low"


def test_settings_search_provider_round_trips(client):
    client.put("/settings", json={"search_provider": "searxng", "searxng_url": "http://localhost:8888"})
    got = client.get("/settings").json()
    assert got["search_provider"] == "searxng"
    assert got["searxng_url"] == "http://localhost:8888"
