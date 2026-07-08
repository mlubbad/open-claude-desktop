"""BigQuery is an opt-in builtin: a general (unconfigured) install must not advertise
it or run Google auth, and connector auth-failures are tagged so the agent doesn't
hallucinate about the app (the three reported symptoms in part-2 of the demo)."""
from ocd_core import config, integrations


def test_bigquery_hidden_when_not_configured(monkeypatch):
    monkeypatch.setattr(config, "BIGQUERY_ENABLED", False)
    # Even if get_bq_client would explode (stale gcloud creds), it must never be called.
    def _boom():
        raise AssertionError("get_bq_client must not run when BigQuery is disabled")
    monkeypatch.setattr(integrations.bigquery, "get_bq_client", _boom)
    ids = [c["id"] for c in integrations.list_connectors()]
    assert "bigquery" not in ids
    assert "web" in ids  # the general builtins still show


def test_bigquery_shown_when_configured(monkeypatch):
    monkeypatch.setattr(config, "BIGQUERY_ENABLED", True)
    monkeypatch.setattr(config, "PROJECT_ID", "demo-proj")
    monkeypatch.setattr(integrations.bigquery, "get_bq_client", lambda: object())
    conns = {c["id"]: c for c in integrations.list_connectors()}
    assert conns["bigquery"]["status"] == "connected"


def test_auth_failure_result_is_tagged():
    tagged = integrations._tag_auth_failure(
        "Reauthentication is needed. Please run `gcloud auth application-default login`.")
    assert "TOOL UNAVAILABLE" in tagged
    assert "Do NOT infer" in tagged
    # A normal result is untouched.
    assert integrations._tag_auth_failure("3 tables: a, b, c") == "3 tables: a, b, c"
