from fastapi.testclient import TestClient

from backend.app.main import app

client = TestClient(app)


def test_cors_allows_known_origin():
    r = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_rejects_unknown_origin():
    r = client.get("/health", headers={"Origin": "http://evil.example"})
    assert r.headers.get("access-control-allow-origin") != "http://evil.example"
