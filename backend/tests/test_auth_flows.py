"""Agent-assisted connector auth (host login CLI flows).

The real login commands (gcloud/gh/aws) are never run in tests — the streaming
subprocess helper is stubbed to simulate a CLI that prints a consent URL and exits.
"""
from ocd_core import auth_flows, config, integrations, permissions


def test_match_flow_resolves_hints():
    assert auth_flows.match_flow("gcloud-adc") == "gcloud-adc"
    # The exact error string from the reported BigQuery session resolves to ADC.
    assert auth_flows.match_flow(
        "Reauthentication is needed. Please run `gcloud auth application-default login`"
    ) == "gcloud-adc"
    assert auth_flows.match_flow("bigquery") == "gcloud-adc"
    assert auth_flows.match_flow("github") == "github"
    assert auth_flows.match_flow("aws sso") == "aws-sso"
    assert auth_flows.match_flow("") is None
    assert auth_flows.match_flow("totally unrelated") is None


def test_authenticate_is_sensitive():
    """The tool must always pass the HITL gate — never run a host login silently."""
    assert permissions.is_sensitive("authenticate") is True
    assert permissions.requires_approval("authenticate", "ask") is True


def test_list_flows_flags_availability(monkeypatch):
    monkeypatch.setattr(auth_flows.shutil, "which", lambda cli: "/usr/bin/" + cli if cli == "gcloud" else None)
    flows = {f["id"]: f for f in auth_flows.list_flows()}
    assert flows["gcloud-adc"]["available"] is True
    assert flows["github"]["available"] is False


def test_run_flow_streams_output_and_surfaces_url(monkeypatch):
    monkeypatch.setattr(config, "AUTH_FLOWS_ENABLED", True)
    monkeypatch.setattr(auth_flows.shutil, "which", lambda cli: "/usr/bin/gcloud")

    captured_cmd = {}

    def fake_stream(cmd, cwd, env, on_output, timeout, popen_extra=None, **kw):
        captured_cmd["cmd"] = cmd
        # Simulate gcloud printing the consent link, then exiting 0 after "consent".
        on_output("stderr", "Go to the following link in your browser:\n")
        on_output("stderr", "  https://accounts.google.com/o/oauth2/auth?client_id=x&scope=y\n")
        on_output("stderr", "Credentials saved.\n")
        return 0, "", "Credentials saved.\n", False

    monkeypatch.setattr(integrations, "_stream_subprocess", fake_stream)

    seen = {"lines": [], "url": None}
    res = auth_flows.run_flow(
        "gcloud-adc",
        on_output=lambda s, t: seen["lines"].append(t),
        on_url=lambda u: seen.__setitem__("url", u),
    )
    assert res["ok"] is True
    assert captured_cmd["cmd"] == ["gcloud", "auth", "application-default", "login"]  # fixed
    assert seen["url"] == "https://accounts.google.com/o/oauth2/auth?client_id=x&scope=y"
    assert any("link in your browser" in ln for ln in seen["lines"])  # streamed live


def test_run_flow_missing_cli(monkeypatch):
    monkeypatch.setattr(config, "AUTH_FLOWS_ENABLED", True)
    monkeypatch.setattr(auth_flows.shutil, "which", lambda cli: None)
    res = auth_flows.run_flow("gcloud-adc")
    assert res["ok"] is False and "not installed" in res["detail"]


def test_run_flow_timeout_reports_cleanly(monkeypatch):
    monkeypatch.setattr(config, "AUTH_FLOWS_ENABLED", True)
    monkeypatch.setattr(auth_flows.shutil, "which", lambda cli: "/usr/bin/gcloud")

    def fake_stream(cmd, cwd, env, on_output, timeout, popen_extra=None, **kw):
        on_output("stderr", "https://accounts.google.com/o/oauth2/auth?x\n")
        return -1, "", "", True  # timed_out

    monkeypatch.setattr(integrations, "_stream_subprocess", fake_stream)
    res = auth_flows.run_flow("gcloud-adc")
    assert res["ok"] is False and "timed out" in res["detail"]
    assert res["url"]  # the URL was still surfaced


def test_disabled_refuses(monkeypatch):
    monkeypatch.setattr(config, "AUTH_FLOWS_ENABLED", False)
    assert auth_flows.run_flow("gcloud-adc")["ok"] is False


def test_agent_dispatch_emits_auth_url_and_streams(monkeypatch):
    """The agent's `authenticate` handler resolves the flow, streams output, and emits
    an `auth_url` event so the client opens the browser."""
    import asyncio

    from ocd_core import agent

    def fake_run_flow(flow_id, on_output=None, on_url=None):
        assert flow_id == "gcloud-adc"
        on_output("stderr", "Go to the following link:\n")
        on_url("https://accounts.google.com/o/oauth2/auth?z")
        return {"ok": True, "url": "https://accounts.google.com/o/oauth2/auth?z",
                "detail": "signed in with Google Cloud — Application Default Credentials"}

    monkeypatch.setattr(auth_flows, "run_flow", fake_run_flow)

    events: list[dict] = []
    out = asyncio.run(agent._run_one_tool(
        "authenticate",
        {"provider": "Reauthentication is needed. Run gcloud auth application-default login"},
        "tc1", None, "smoke test bigquery", 5, emit=events.append))

    assert out["ok"] is True
    assert "retry the original tool" in out["result"]
    kinds = [e["type"] for e in events]
    assert "auth_url" in kinds and "tool_output_delta" in kinds
    url_ev = next(e for e in events if e["type"] == "auth_url")
    assert url_ev["provider"] == "gcloud-adc"
    assert url_ev["url"].startswith("https://accounts.google.com")
