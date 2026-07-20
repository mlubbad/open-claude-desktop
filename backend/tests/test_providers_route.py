"""Phase 1: the BYOK providers API lists providers and stores keys without leaking them."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ocd_core import secrets
from ocd_core.llm import client as llm_client


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("OCD_SECRET_BACKEND", "memory")
    secrets.reset_store()
    llm_client.reset_clients()
    from app.routes import providers as providers_route
    app = FastAPI()
    app.include_router(providers_route.router)
    yield TestClient(app)
    secrets.reset_store()
    llm_client.reset_clients()


def test_list_providers_no_key_leak(client, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    body = client.get("/providers").json()
    ids = {p["id"] for p in body}
    assert {"openai", "zhipu", "ollama"} <= ids
    openai = next(p for p in body if p["id"] == "openai")
    assert openai["has_key"] is False
    ollama = next(p for p in body if p["id"] == "ollama")
    assert ollama["has_key"] is True  # local, no key required
    # No endpoint ever exposes a raw key field.
    assert all("key" not in p for p in body)


def test_key_optional_provider_view(client, monkeypatch):
    """Vertex AI renders as key-optional: usable without a key (ADC), with a setup
    hint, and has_key reflecting the stored-token override, not usability."""
    monkeypatch.delenv("VERTEX_AI_ACCESS_TOKEN", raising=False)
    body = client.get("/providers").json()
    vertex = next(p for p in body if p["id"] == "vertex")
    assert vertex["requires_key"] is False
    assert vertex["key_optional"] is True
    assert vertex["key_hint"]
    assert vertex["has_key"] is False
    gemini = next(p for p in body if p["id"] == "gemini")
    assert gemini["requires_key"] is True and gemini["key_optional"] is False
    # Storing a token flips the badge state and never leaks the value.
    client.put("/providers/vertex/key", json={"key": "tok-x"})
    vertex = next(p for p in client.get("/providers").json() if p["id"] == "vertex")
    assert vertex["has_key"] is True and "key" not in vertex


def test_set_and_delete_key(client):
    r = client.put("/providers/openai/key", json={"key": "sk-secret"})
    assert r.json() == {"id": "openai", "has_key": True}
    # Reflected in the list, but the value is never returned.
    body = client.get("/providers").json()
    openai = next(p for p in body if p["id"] == "openai")
    assert openai["has_key"] is True
    r = client.delete("/providers/openai/key")
    assert r.json()["has_key"] is False


def test_provider_models_include_capabilities(client):
    body = client.get("/providers/openai/models").json()
    assert body["id"] == "openai"
    assert any(m["id"] == "gpt-4o" for m in body["models"])
    gpt4o = next(m for m in body["models"] if m["id"] == "gpt-4o")
    assert gpt4o["capabilities"]["vision"] is True


def test_provider_test_route(client, monkeypatch):
    import types
    fake = types.SimpleNamespace(
        chat=types.SimpleNamespace(
            completions=types.SimpleNamespace(create=lambda model, **kw: "ok")))
    monkeypatch.setattr(llm_client, "get_client", lambda pid=None: fake)
    r = client.post("/providers/deepseek/test")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "deepseek" and body["ok"] is True
    assert "Connected" in body["detail"]
