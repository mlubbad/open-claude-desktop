"""Diagnostics snapshot ("Export diagnostics"): useful shape, and — critically — no
secrets and no personal-profile leakage in a bundle the user may share with support."""
import json

from fastapi.testclient import TestClient


def test_collect_shape_and_profile_redaction(db):
    from ocd_core import config, diagnostics, settings
    settings.save_settings({"profile": {"call_me": "Sam", "about": "private notes here"}})

    snap = diagnostics.collect()

    assert snap["app"]["name"] == config.APP_NAME
    assert snap["app"]["backend_version"] == config.BACKEND_VERSION
    assert snap["platform"]["python"] and "system" in snap["platform"]
    assert snap["database"]["scheme"] == "sqlite"           # scheme only, never the full URL
    assert snap["database"]["reachable"] is True
    assert set(snap["counts"]) == {"projects", "conversations", "schedules", "cowork_tasks"}
    # The profile is reduced to a presence flag; its contents never ship.
    assert snap["settings"]["profile"] == {"present": True}
    assert "private notes here" not in json.dumps(snap)


def test_collect_never_carries_a_full_database_url(db, monkeypatch):
    """Guard: even a URL with credentials is reduced to its scheme."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://user:pw@db.internal:5432/app")
    from ocd_core.db import engine
    engine.reset_engine()
    from ocd_core import diagnostics
    snap = diagnostics.collect()
    assert snap["database"]["scheme"] == "postgresql"
    assert "pw@db.internal" not in json.dumps(snap)
    engine.reset_engine()


def test_diagnostics_route_returns_snapshot(db):
    from app.main import app
    c = TestClient(app)
    r = c.get("/diagnostics")
    assert r.status_code == 200
    assert r.json()["app"]["backend_version"]


def test_diagnostics_route_requires_auth(monkeypatch):
    monkeypatch.setenv("APP_USERNAME", "u")
    monkeypatch.setenv("APP_PASSWORD", "p")
    monkeypatch.setenv("CHAINLIT_AUTH_SECRET", "s")
    from app.main import app
    c = TestClient(app)
    assert c.get("/diagnostics").status_code == 401       # unlike /healthz, it's gated
    assert c.get("/healthz").status_code == 200
