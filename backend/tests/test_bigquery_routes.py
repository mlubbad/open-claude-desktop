"""Tests for the BigQuery status/reconnect routes."""
from __future__ import annotations

from app.routes import bigquery as bq_route
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ocd_core import bigquery


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(bq_route.router)
    return TestClient(app)


def test_status_connected(monkeypatch):
    monkeypatch.setattr(bigquery, "_dry_run", lambda sql: (True, "SELECT", 0, [], None))
    body = _client().get("/bigquery/status").json()
    assert body["connected"] is True
    assert body["auth_expired"] is False
    assert body["project"]  # non-empty project id


def test_status_auth_expired_self_heals(monkeypatch):
    monkeypatch.setattr(bigquery, "_dry_run",
                        lambda sql: (False, None, 0, [], "Reauthentication is needed."))
    reset = {"called": False}
    monkeypatch.setattr(bigquery, "reset_bq_client",
                        lambda: reset.__setitem__("called", True))
    body = _client().get("/bigquery/status").json()
    assert body["connected"] is False
    assert body["auth_expired"] is True
    assert reset["called"] is True  # tried to rebuild from fresh ADC


def test_reconnect_spawns_gcloud(monkeypatch):
    spawned = {"cmd": None}
    monkeypatch.setattr(bq_route.shutil, "which", lambda name: "/usr/bin/gcloud")
    monkeypatch.setattr(bq_route.subprocess, "Popen",
                        lambda cmd, *a, **k: spawned.__setitem__("cmd", cmd))
    reset = {"called": False}
    monkeypatch.setattr(bigquery, "reset_bq_client",
                        lambda: reset.__setitem__("called", True))
    body = _client().post("/bigquery/reconnect").json()
    assert body["started"] is True
    assert spawned["cmd"][1:] == ["auth", "application-default", "login"]
    assert reset["called"] is True


def test_reconnect_gcloud_missing(monkeypatch):
    monkeypatch.setattr(bq_route.shutil, "which", lambda name: None)
    body = _client().post("/bigquery/reconnect").json()
    assert body["started"] is False
    assert "gcloud" in body["error"]
