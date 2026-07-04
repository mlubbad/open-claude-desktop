from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_cors_allows_known_origin():
    r = client.get("/healthz", headers={"Origin": "http://localhost:3000"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_cors_rejects_unknown_origin():
    r = client.get("/healthz", headers={"Origin": "http://evil.example"})
    assert r.headers.get("access-control-allow-origin") != "http://evil.example"
