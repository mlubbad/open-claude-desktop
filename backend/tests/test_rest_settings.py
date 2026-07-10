import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(db):
    from app.main import app
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


def test_settings_visible_models_round_trips(client):
    """The chat picker's per-provider model curation persists ({} default = show few)."""
    assert client.get("/settings").json().get("visible_models") == {}
    client.put("/settings", json={"visible_models": {"zhipu": ["glm-5.2", "glm-4.6"]}})
    assert client.get("/settings").json()["visible_models"] == {"zhipu": ["glm-5.2", "glm-4.6"]}
