"""Tests for the in-app BigQuery reconnect helpers (ocd_core.bigquery)."""
from __future__ import annotations

import pytest
from ocd_core import bigquery


@pytest.mark.parametrize("err", [
    "Reauthentication is needed. Please run `gcloud auth application-default login`",
    "Reauthentication failed. cannot refresh token",
    "('invalid_grant: Token has been expired or revoked.')",
    "google.auth.exceptions.RefreshError: invalid_grant",
    "Could not automatically determine credentials.",
    "invalid_rapt token; reauth required",
])
def test_needs_reauth_true_for_expiry_signatures(err):
    assert bigquery.needs_reauth(err) is True


@pytest.mark.parametrize("err", [
    "400 ... ProjectId must be non-empty",
    "Syntax error: Unexpected end of script",
    "Access Denied: Table analytics.foo",
    "",
])
def test_needs_reauth_false_for_unrelated_errors(err):
    assert bigquery.needs_reauth(err) is False


def test_reset_bq_client_clears_cache():
    bigquery._bq_client = object()  # simulate a cached (stale) client
    bigquery.reset_bq_client()
    assert bigquery._bq_client is None


def test_execute_sql_flags_auth_expired(monkeypatch):
    # Dry-run fails with an ADC-expiry error -> result is flagged auth_expired.
    monkeypatch.setattr(bigquery, "_dry_run",
                        lambda sql: (False, None, 0, [], "Reauthentication is needed."))
    res = bigquery.execute_sql("SELECT 1")
    assert res["ok"] is False
    assert res["auth_expired"] is True


def test_execute_sql_not_auth_expired_for_other_errors(monkeypatch):
    monkeypatch.setattr(bigquery, "_dry_run",
                        lambda sql: (False, "SELECT", 0, [], "Syntax error near 'FROM'"))
    res = bigquery.execute_sql("SELECT 1")
    assert res["ok"] is False
    assert res["auth_expired"] is False
