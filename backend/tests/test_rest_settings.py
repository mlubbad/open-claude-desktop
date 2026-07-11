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


def test_opik_settings_change_clears_the_tracing_failure_latch(client):
    """After tracing fails once (e.g. SDK missing), the one-way latch must reset
    when the user changes any opik_* setting — otherwise fixing the setup silently
    requires a backend restart. A non-opik save must NOT reset it."""
    from ocd_core import opik_tracing
    try:
        opik_tracing._state["failed"] = True
        client.put("/settings", json={"effort": "Low"})
        assert opik_tracing._state["failed"] is True  # unrelated saves keep the latch
        client.put("/settings", json={"opik_enabled": True})
        assert opik_tracing._state["failed"] is False
    finally:
        opik_tracing.reset_for_tests()
