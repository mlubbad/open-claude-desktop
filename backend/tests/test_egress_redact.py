"""Deterministic outbound redaction (T2-Item2c): defense-in-depth against
prompt-injection exfil. Strips recognizable secret SHAPES (API keys, tokens,
private keys) out of AGENT-CONTROLLED outbound content -- web_fetch's URL
query, web_search's query, and MCP tool args -- before it ever leaves the
process, even to an approved/trusted destination.

Deliberately "redact, don't block": a false positive just masks a substring
in a request the agent already chose to send; it never fails the request.

Headers are OUT OF SCOPE and must never be touched: the app legitimately
sends the USER's own keys to configured endpoints via Authorization/auth
headers (connectors, MCP OAuth), and redacting those would break them.
"""
from __future__ import annotations

import httpx
import pytest
from ocd_core import egress, egress_redact, integrations, observability

# --------------------------------------------------------------------------- #
# Part 1 -- redact_secrets / redact_obj (pure, no network)
# --------------------------------------------------------------------------- #

_SAMPLES = {
    "pem": ("-----BEGIN PRIVATE KEY-----\n"
            "MIIBVwIBADANBgkqhkiG9w0BAQEFAASCAT8wggE7AgEAAkEA...\n"
            "-----END PRIVATE KEY-----"),
    "pem_rsa": ("-----BEGIN RSA PRIVATE KEY-----\n"
                "MIIBVwIBADANBgkqhkiG9w0BAQEFAASCAT8wggE7AgEAAkEA...\n"
                "-----END RSA PRIVATE KEY-----"),
    "jwt": ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIn0."
            "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"),
    "anthropic": "sk-ant-" + "A" * 40,
    "openai_proj": "sk-proj-" + "B" * 40,
    "groq": "gsk_" + "C" * 40,
    "github": "ghp_" + "D" * 40,
    "aws": "AKIA" + "E" * 16,
    "google": "AIza" + "F" * 35,
    "slack": "xoxb-" + "1234567890",
    "openai_generic": "sk-" + "G" * 40,
}


@pytest.mark.parametrize("name", list(_SAMPLES))
def test_redact_secrets_masks_each_known_shape(name):
    secret = _SAMPLES[name]
    out, n = egress_redact.redact_secrets(secret)
    assert n == 1
    assert secret not in out
    assert out == "«redacted-secret»"


def test_redact_secrets_most_specific_pattern_wins_for_anthropic_key():
    # sk-ant-... must be consumed whole by the specific pattern -- not leave a
    # residual tail for the generic trailing sk- pattern to also match.
    secret = "sk-ant-" + "A" * 40
    out, n = egress_redact.redact_secrets(f"key={secret}")
    assert n == 1
    assert out == "key=«redacted-secret»"


def test_redact_secrets_most_specific_pattern_wins_for_openai_project_key():
    secret = "sk-proj-" + "B" * 40
    out, n = egress_redact.redact_secrets(f"key={secret}")
    assert n == 1
    assert out == "key=«redacted-secret»"


def test_redact_secrets_masks_multiple_distinct_secrets_in_one_string():
    a = "sk-ant-" + "A" * 40
    b = "AKIA" + "E" * 16
    out, n = egress_redact.redact_secrets(f"first {a} then {b} done")
    assert n == 2
    assert a not in out and b not in out
    assert out == "first «redacted-secret» then «redacted-secret» done"


@pytest.mark.parametrize("benign", [
    "The quick brown fox jumps over the lazy dog.",
    "https://example.com/search?q=weather+today",
    "550e8400-e29b-41d4-a716-446655440000",              # UUID
    "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b0",           # 40-char git SHA
    "",
])
def test_redact_secrets_leaves_benign_text_untouched(benign):
    out, n = egress_redact.redact_secrets(benign)
    assert out == benign
    assert n == 0


def test_redact_secrets_never_raises_on_non_string_input():
    # Best-effort contract: garbage input degrades to a no-op, never an exception.
    out, n = egress_redact.redact_secrets(None)  # type: ignore[arg-type]
    assert n == 0
    assert out is None


def test_redact_obj_walks_nested_dicts_and_lists():
    secret = "sk-ant-" + "A" * 40
    obj = {"a": [1, "clean", {"b": secret}], "c": secret, "d": 3, "e": None, "f": True}
    out, n = egress_redact.redact_obj(obj)
    assert n == 2
    assert out["a"][2]["b"] == "«redacted-secret»"
    assert out["c"] == "«redacted-secret»"
    assert out["a"][0] == 1 and out["a"][1] == "clean"
    assert out["d"] == 3 and out["e"] is None and out["f"] is True
    # Original object must be untouched -- redact_obj returns a COPY.
    assert obj["c"] == secret


def test_redact_obj_passthrough_for_scalars():
    assert egress_redact.redact_obj(5) == (5, 0)
    assert egress_redact.redact_obj(None) == (None, 0)
    assert egress_redact.redact_obj(True) == (True, 0)


# --------------------------------------------------------------------------- #
# Part 2 -- web_fetch: redact the query of the AGENT-supplied URL
# --------------------------------------------------------------------------- #

class _FetchOKResp:
    status_code = 200
    headers = {"content-type": "text/html"}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_bytes(self):
        yield b"<html><title>Hi</title>body</html>"


def _fake_pinned_client(monkeypatch, captured):
    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, method, url, headers=None):
            captured["url"] = url
            captured["headers"] = headers
            return _FetchOKResp()

    monkeypatch.setattr(egress, "assert_public_url", lambda u, **k: u)
    monkeypatch.setattr(egress, "pinned_client", lambda **k: _Client())


def test_web_fetch_redacts_secret_from_query(monkeypatch):
    captured = {}
    _fake_pinned_client(monkeypatch, captured)
    events = []
    monkeypatch.setattr(observability, "audit", lambda e: events.append(e))
    integrations._FETCH_CACHE.clear()

    secret = "sk-ant-" + "A" * 40
    out, _sources = integrations.web_fetch(f"https://example.com/x?leak={secret}&safe=1")

    assert secret not in captured["url"]
    assert captured["url"].startswith("https://example.com/x?")  # host/path intact
    assert "safe=1" in captured["url"]                            # other params intact
    assert "«redacted-secret»" in captured["url"]
    assert out.startswith("Fetched")
    assert secret not in out  # not echoed back into the agent's tool result either
    assert any(e.get("event") == "egress_redaction" and e.get("tool") == "web_fetch"
              and e.get("count", 0) > 0 for e in events)


def test_web_fetch_leaves_a_clean_query_untouched(monkeypatch):
    captured = {}
    _fake_pinned_client(monkeypatch, captured)
    events = []
    monkeypatch.setattr(observability, "audit", lambda e: events.append(e))
    integrations._FETCH_CACHE.clear()

    out, _ = integrations.web_fetch("https://example.com/search?q=weather+today")

    assert captured["url"] == "https://example.com/search?q=weather+today"
    assert not any(e.get("event") == "egress_redaction" for e in events)
    assert out.startswith("Fetched")


# --------------------------------------------------------------------------- #
# Part 3 -- web_search: redact the query before it reaches DDG / SearXNG
# --------------------------------------------------------------------------- #

def test_ddg_html_results_redacts_secret_from_query(monkeypatch):
    captured = {}

    class _Resp:
        text = "<html></html>"

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, data=None, headers=None):
            captured["data"] = data
            captured["headers"] = headers
            return _Resp()

    monkeypatch.setattr(egress, "pinned_client", lambda **k: _Client())
    events = []
    monkeypatch.setattr(observability, "audit", lambda e: events.append(e))

    secret = "sk-ant-" + "B" * 40
    integrations._ddg_html_results(f"weather in paris {secret}", 5)

    assert secret not in captured["data"]["q"]
    assert "«redacted-secret»" in captured["data"]["q"]
    assert "weather in paris" in captured["data"]["q"]
    assert any(e.get("event") == "egress_redaction" and e.get("tool") == "web_search"
              for e in events)


def test_ddg_html_results_leaves_a_clean_query_untouched(monkeypatch):
    captured = {}

    class _Resp:
        text = "<html></html>"

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, data=None, headers=None):
            captured["data"] = data
            return _Resp()

    monkeypatch.setattr(egress, "pinned_client", lambda **k: _Client())
    integrations._ddg_html_results("weather today", 5)
    assert captured["data"]["q"] == "weather today"


def test_searxng_results_redacts_secret_from_query(monkeypatch):
    captured = {}

    class _Resp:
        def json(self):
            return {"results": []}

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None, headers=None):
            captured["params"] = params
            captured["headers"] = headers
            return _Resp()

    monkeypatch.setattr(httpx, "Client", lambda *a, **k: _Client())
    events = []
    monkeypatch.setattr(observability, "audit", lambda e: events.append(e))

    secret = "sk-ant-" + "C" * 40
    integrations._searxng_results(f"weather {secret}", 5, "http://127.0.0.1:8888")

    assert secret not in captured["params"]["q"]
    assert "«redacted-secret»" in captured["params"]["q"]
    assert any(e.get("event") == "egress_redaction" and e.get("tool") == "web_search"
              for e in events)


# --------------------------------------------------------------------------- #
# Part 4 -- MCP tool args: redact the agent-supplied `args` right before the
# call reaches the registry. The SAME scenario proves the cheapest and most
# direct thing of all: server cfg/headers (app config, resolved from the
# keychain -- never agent-controlled) are NEVER touched, even when they are
# themselves shaped like a secret (a real Bearer token).
# --------------------------------------------------------------------------- #

def _mcp_server(schema_props):
    return {"id": "desktop", "name": "Desktop", "url": "https://mcp.example/x",
            "tools": [{"name": "Click",
                      "inputSchema": {"type": "object", "properties": schema_props}}]}


def test_call_mcp_redacts_args_but_never_touches_cfg_or_headers(monkeypatch):
    secret_in_arg = "sk-ant-" + "D" * 40
    secret_in_header = "sk-ant-" + "E" * 40  # the user's OWN key, legitimately sent as auth
    resolved_cfg = {"id": "desktop", "url": "https://mcp.example/x",
                    "headers": {"Authorization": f"Bearer {secret_in_header}"}}
    server = _mcp_server({"note": {"type": "string"}})

    monkeypatch.setattr(integrations, "_load_mcp_servers", lambda: [server])
    monkeypatch.setattr(integrations, "_resolve_cfg", lambda s: resolved_cfg)
    seen = {}

    def _fake_call(cfg, tool, args):
        seen["cfg"], seen["tool"], seen["args"] = cfg, tool, args
        return "ok"

    monkeypatch.setattr(integrations.mcp_registry.registry, "call", _fake_call)
    events = []
    monkeypatch.setattr(observability, "audit", lambda e: events.append(e))

    out = integrations.call_mcp("mcp_desktop_Click", {"note": f"leak {secret_in_arg} please"})

    assert out == "ok"
    assert seen["tool"] == "Click"
    # Agent-controlled arg IS redacted:
    assert secret_in_arg not in seen["args"]["note"]
    assert "«redacted-secret»" in seen["args"]["note"]
    assert "leak" in seen["args"]["note"] and "please" in seen["args"]["note"]
    # App config / auth header is NEVER touched, even though it is itself
    # shaped like a secret:
    assert seen["cfg"]["headers"]["Authorization"] == f"Bearer {secret_in_header}"
    assert any(e.get("event") == "egress_redaction" and e.get("tool") == "mcp"
              and e.get("count", 0) > 0 for e in events)


def test_call_mcp_without_secrets_passes_args_through_unchanged(monkeypatch):
    server = _mcp_server({"note": {"type": "string"}})
    monkeypatch.setattr(integrations, "_load_mcp_servers", lambda: [server])
    monkeypatch.setattr(integrations, "_resolve_cfg", lambda s: s)
    seen = {}

    def _fake_call(cfg, tool, args):
        seen["args"] = args
        return "ok"

    monkeypatch.setattr(integrations.mcp_registry.registry, "call", _fake_call)
    events = []
    monkeypatch.setattr(observability, "audit", lambda e: events.append(e))

    integrations.call_mcp("mcp_desktop_Click", {"note": "just a normal note"})

    assert seen["args"] == {"note": "just a normal note"}
    assert not any(e.get("event") == "egress_redaction" for e in events)


def test_call_mcp_redacts_nested_args():
    """coerce_args_to_schema can turn a stringified array/object into a real
    list/dict; redact_obj must walk that structure too (not just top-level
    string values)."""
    secret = "sk-ant-" + "F" * 40
    schema_props = {"payload": {"type": "object"}}
    server = _mcp_server(schema_props)
    from unittest.mock import patch

    import ocd_core.integrations as I
    with patch.object(I, "_load_mcp_servers", lambda: [server]), \
         patch.object(I, "_resolve_cfg", lambda s: s):
        seen = {}

        def _fake_call(cfg, tool, args):
            seen["args"] = args
            return "ok"

        with patch.object(I.mcp_registry.registry, "call", _fake_call):
            I.call_mcp("mcp_desktop_Click",
                       {"payload": f'{{"note": "leak {secret} here"}}'})

    assert secret not in seen["args"]["payload"]["note"]
    assert "«redacted-secret»" in seen["args"]["payload"]["note"]


# --------------------------------------------------------------------------- #
# Review MINOR_GAPS: two adjacent paths that echoed the RAW secret even though
# the outbound content was redacted -- the blocked-host AUDIT log, and the
# no-results message reflected back into the transcript. Both now redact first.
# --------------------------------------------------------------------------- #


def test_web_fetch_blocked_host_audit_does_not_log_the_secret(monkeypatch):
    events = []
    monkeypatch.setattr(observability, "audit", lambda e: events.append(e))
    integrations._FETCH_CACHE.clear()
    secret = "sk-ant-" + "A" * 40
    # A literal metadata IP is blocked by assert_public_url (link-local), so we
    # hit the egress_blocked audit path -- with a secret in the query.
    out, _ = integrations.web_fetch(f"http://169.254.169.254/x?key={secret}")
    assert "url_not_allowed" in out
    blocked = [e for e in events if e.get("event") == "egress_blocked"]
    assert blocked, "expected an egress_blocked audit event"
    assert secret not in blocked[0].get("url", ""), "secret leaked into the audit log"


def test_web_search_no_results_message_does_not_echo_the_secret(monkeypatch):
    # Force the zero-results branch so _format_web_block reflects the query back.
    monkeypatch.setattr(integrations, "_web_results", lambda q, n=5: [])
    secret = "gsk_" + "B" * 40
    out = integrations.web_search(f"please look up {secret}")
    assert secret not in out
    assert "«redacted-secret»" in out  # the query was masked in the echoed message
