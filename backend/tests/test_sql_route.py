"""The direct SQL route (/sql/execute) must apply the same per-user rate limit as
/agent/turn before it reaches BigQuery. current_user is overridden so these tests
are independent of ambient auth; BigQuery is never touched (execute_sql is faked).
"""
from __future__ import annotations

from app.deps import current_user
from app.routes import sql as sql_route
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ocd_core import bigquery, observability


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(sql_route.router)
    app.dependency_overrides[current_user] = lambda: "tester"
    return TestClient(app)


def test_sql_execute_rate_limited(monkeypatch):
    monkeypatch.setattr(observability, "check_rate_limit", lambda user: False)
    calls = {"n": 0}

    def _fake_exec(sql, project=None):
        calls["n"] += 1
        return {"ok": True}

    monkeypatch.setattr(bigquery, "execute_sql", _fake_exec)
    r = _client().post("/sql/execute", json={"sql": "SELECT 1"})
    assert r.status_code == 429
    assert calls["n"] == 0  # execute_sql must not run once rate-limited


def test_sql_execute_allowed_calls_execute(monkeypatch):
    monkeypatch.setattr(observability, "check_rate_limit", lambda user: True)
    seen = {}

    def _fake_exec(sql, project=None):
        seen.update(sql=sql, project=project)
        return {"ok": True, "rows": []}

    monkeypatch.setattr(bigquery, "execute_sql", _fake_exec)
    r = _client().post("/sql/execute", json={"sql": "SELECT 1", "project": "p1"})
    assert r.status_code == 200
    assert seen == {"sql": "SELECT 1", "project": "p1"}
