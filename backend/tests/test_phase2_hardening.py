"""Phase 2a backend hardening (production-readiness audit follow-up).

Covers: memory-mutation gating, host-exec fallback guard, ollama default model, atomic
pre-migration backup, DB-fallback honesty in /readyz + diagnostics, and the cheap
conversation COUNT."""
import pytest


# ---- memory mutation gating --------------------------------------------------------
def test_memory_mutations_are_gated_in_ask_mode_but_view_is_not():
    from ocd_core import permissions
    # Read-only view stays ungated (same class as web_search / search_schema).
    assert permissions.requires_approval("memory", "ask", {"command": "view"}) is False
    # Every mutating command is gated in ask mode.
    for cmd in ("create", "str_replace", "insert", "delete", "rename"):
        assert permissions.requires_approval("memory", "ask", {"command": cmd}) is True, cmd
    # No/garbage args → not gated (a malformed call no-ops in the tool anyway).
    assert permissions.requires_approval("memory", "ask", None) is False
    # auto never prompts; strict always does.
    assert permissions.requires_approval("memory", "auto", {"command": "delete"}) is False
    assert permissions.requires_approval("memory", "strict", {"command": "view"}) is True


# ---- host-exec fallback guard ------------------------------------------------------
def test_host_exec_is_refused_when_disabled(monkeypatch):
    from ocd_core import integrations
    monkeypatch.setattr(integrations, "_code_execution_mode", lambda: "auto")
    monkeypatch.setattr(integrations.shutil, "which", lambda _n: None)  # no docker
    monkeypatch.setenv("OCD_NO_HOST_EXEC", "1")
    r = integrations.execute_code("print('should not run')")
    assert r["ok"] is False and r["engine"] == "host-disabled"


# ---- ollama default model ----------------------------------------------------------
def test_ollama_default_is_a_real_model():
    from ocd_core.llm import providers
    ol = providers.get_provider("ollama")
    assert ol.default_model != "fast-mistral"
    assert "fast-mistral" not in ol.models
    assert ol.default_model in ol.models  # the default is one of the offered tags


# ---- atomic pre-migration backup ---------------------------------------------------
def test_backup_is_atomic_and_a_failure_keeps_the_prior_snapshot(tmp_path, monkeypatch):
    from ocd_core.db import engine
    dbfile = tmp_path / "ocd.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{dbfile.as_posix()}")
    engine.reset_engine()
    try:
        with engine.get_engine().begin() as c:
            c.exec_driver_sql("CREATE TABLE t (x)")
            c.exec_driver_sql("INSERT INTO t VALUES (1)")
        bak = engine.backup_sqlite_before_migration()
        assert bak is not None and bak.exists() and bak.stat().st_size > 0
        # A later FAILED backup must RAISE (so the caller aborts the migration) and must
        # NOT destroy the good snapshot it wrote before.
        monkeypatch.setattr(engine, "get_engine",
                            lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        with pytest.raises(RuntimeError):
            engine.backup_sqlite_before_migration()
        assert bak.exists() and bak.stat().st_size > 0  # prior recovery point intact
    finally:
        monkeypatch.undo()
        engine.reset_engine()


# ---- DB-fallback honesty -----------------------------------------------------------
def test_readyz_reports_degraded_on_fallback(monkeypatch, db):
    # `db` pins DATABASE_URL to an isolated in-memory SQLite so the healthy baseline
    # probe hits a real, reachable DB. Without it, /readyz probes whatever the ambient
    # environment configures (e.g. a dev .env Postgres that isn't running), and the
    # "ready" baseline flakes to "unavailable" — like its siblings test_diagnostics /
    # test_count_all_conversations, this test needs the isolated DB.
    from app.main import app
    from fastapi.testclient import TestClient
    from ocd_core.db import engine
    c = TestClient(app)
    # Healthy: ready.
    assert c.get("/readyz").json()["status"] == "ready"
    # Fallback active → 503 degraded with configured vs active backends.
    monkeypatch.setattr(engine, "fell_back", lambda: True)
    monkeypatch.setattr(engine, "active_database_url", lambda: "sqlite:///x")
    monkeypatch.setattr(engine, "database_url", lambda: "postgresql://h/db")
    r = c.get("/readyz")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "degraded"
    assert body["configured_backend"] == "postgresql" and body["active_backend"] == "sqlite"


def test_diagnostics_reports_configured_and_active_db(db):
    from ocd_core import diagnostics
    snap = diagnostics.collect()
    d = snap["database"]
    assert {"configured_scheme", "active_scheme", "fell_back", "reachable"} <= set(d)
    assert d["fell_back"] is False  # test DB is the real (in-memory) engine, no fallback


def test_count_all_conversations(db):
    from ocd_core import conversations
    assert conversations.count_all_conversations() == 0
    conversations.create_conversation("p1", "one")
    conversations.create_conversation("p1", "two")
    assert conversations.count_all_conversations() == 2
