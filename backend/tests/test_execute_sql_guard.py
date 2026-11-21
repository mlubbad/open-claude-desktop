"""Guard-path tests for ocd_core.bigquery.execute_sql.

These exercise the read-only SQL guard WITHOUT touching BigQuery or the network.
The dry-run (and therefore the real client) is faked via monkeypatch, and we
assert that guard rejections that happen before the dry-run never construct a
client at all. Return shapes are pinned to the real execute_sql contract (the
exact dict keys it returns in core.py before this move).
"""
import importlib

import pytest


@pytest.fixture
def bq(monkeypatch, tmp_path):
    monkeypatch.setenv("OCD_DATA_DIR", str(tmp_path))
    import ocd_core.config as c
    importlib.reload(c)
    import ocd_core.bigquery as b
    importlib.reload(b)
    return b


def _boom_client():
    raise AssertionError("get_bq_client must NOT be called on a guard rejection")


def test_empty_sql_rejected_without_client(bq, monkeypatch):
    monkeypatch.setattr(bq, "get_bq_client", _boom_client)
    out = bq.execute_sql("   ")
    assert out["ok"] is False
    assert out["error"] == "empty"
    assert out["agent_text"] == "No SQL provided."


def test_banned_alias_rejected_before_any_client_call(bq, monkeypatch):
    # A banned reserved-word alias is caught before the dry-run, so the client
    # is never constructed. Wire both the client and the dry-run to explode.
    monkeypatch.setattr(bq, "get_bq_client", _boom_client)
    monkeypatch.setattr(
        bq, "_dry_run",
        lambda sql: (_ for _ in ()).throw(
            AssertionError("dry-run must not run on an alias rejection")),
    )
    out = bq.execute_sql("SELECT 1 AS rows")
    assert out["ok"] is False
    assert out["error"] == "alias"
    assert out["agent_text"].startswith("SQL REJECTED: Banned alias(es) detected: rows")


def test_mutation_is_blocked_after_dry_run(bq, monkeypatch):
    # The mutation check runs on the dry-run's statement_type. Fake the dry-run
    # so it classifies DELETE as a non-SELECT mutation; the real client/query
    # must never be reached for execution.
    monkeypatch.setattr(bq, "_dry_run", lambda sql: (True, "DELETE", 0, [], None))
    monkeypatch.setattr(bq, "get_bq_client", _boom_client)
    out = bq.execute_sql("DELETE FROM analytics.events WHERE 1=1")
    assert out["ok"] is False
    assert out["stmt"] == "DELETE"
    assert out["error"] == "mutation_blocked"
    assert "read-only analytics" in out["agent_text"]


def test_dry_run_validation_failure_is_surfaced(bq, monkeypatch):
    # A failed dry-run (e.g. syntax error) is reported, never executed.
    monkeypatch.setattr(bq, "_dry_run", lambda sql: (False, None, 0, [], "Syntax error"))
    monkeypatch.setattr(bq, "get_bq_client", _boom_client)
    out = bq.execute_sql("SELECT bogus(")
    assert out["ok"] is False
    assert out["error"] == "Syntax error"
    assert out["agent_text"].startswith("VALIDATION FAILED")
