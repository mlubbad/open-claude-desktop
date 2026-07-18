"""web_fetch and web_search bypassed the Item-1 DNS-pinning hardening entirely --
they built their own raw ``httpx`` clients, so ``web_fetch`` still had the exact
DNS-rebind TOCTOU that `_PinnedHTTPTransport` was built to close (validate one
resolution, connect on a second, independent one that an attacker's resolver can
flip to a private/metadata address).

This closes that gap by routing web_fetch and DDG through
``egress.pinned_client()`` (connect-time pin, same mechanism as `safe_get`) and
web_fetch's pre-flight checks through ``egress.assert_public_url`` (domain/port
policy). SearXNG is deliberately left off the pinned path: its base_url is
trusted config (a user setting, can legitimately be a loopback self-host), so it
only gets `follow_redirects=False` to stop a redirect-to-internal SSRF driven by
the agent-controlled query.

Reuses the harness proven in test_egress_toctou.py: `_dns_sequence` gives a
different `getaddrinfo` answer per call (simulating a rebind), and spying on
`httpcore.SyncBackend.connect_tcp` -- the real network layer -- is the ground
truth for "what IP would actually be dialed".
"""
from __future__ import annotations

import socket

import httpcore
import httpx
from ocd_core import egress, integrations


def _dns_sequence(monkeypatch, *answers: str):
    """Each successive call to socket.getaddrinfo returns the next address in
    `answers` (repeating the last one once exhausted). Lets a test give the
    pre-flight lookup(s) a different answer than the pinned backend's own
    connect-time lookup -- simulating a rebind."""
    calls = {"n": 0}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        index = min(calls["n"], len(answers) - 1)
        calls["n"] += 1
        address = answers[index]
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    return calls


# ---------------------------------------------------------------------------
# pinned_client: the public factory
# ---------------------------------------------------------------------------


def test_pinned_client_builds_an_httpx_client_with_the_pinned_transport():
    client = egress.pinned_client()
    assert isinstance(client._transport, egress._PinnedHTTPTransport)


# ---------------------------------------------------------------------------
# web_fetch: proof of the pin -- a rebind that survives every pre-flight check
# (both getting a consistent PUBLIC answer) must still be blocked at the
# moment the pinned transport actually resolves-to-connect, and the real
# network layer must never be asked to dial the private address.
# ---------------------------------------------------------------------------


def test_web_fetch_rebind_between_validation_and_connect_is_blocked(monkeypatch):
    # Both pre-flight assert_public_url checks (the one before the redirect loop,
    # and the per-hop one for hop 1) see a consistent PUBLIC answer -- exactly
    # what a patient rebinding attacker would serve until the real connect.
    # Only the pinned transport's OWN connect-time resolution (the 3rd getaddrinfo
    # call) flips to the private answer.
    _dns_sequence(monkeypatch, "8.8.8.8", "8.8.8.8", "127.0.0.1")

    reached_real_network = []

    def spy_connect_tcp(self, host, *args, **kwargs):
        reached_real_network.append(host)
        raise AssertionError("must not reach the real network layer")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", spy_connect_tcp)

    integrations._FETCH_CACHE.clear()
    out, sources = integrations.web_fetch("https://attacker.test/x")

    assert "url_not_allowed" in out
    assert sources == []
    assert reached_real_network == []  # the private answer never reached a real dial


def test_web_fetch_uses_the_pinned_transport(monkeypatch):
    _dns_sequence(monkeypatch, "8.8.8.8")
    captured = {}

    class _FakeResp:
        status_code = 200
        headers = {"content-type": "text/html"}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_bytes(self):
            yield b"<html><title>Hi</title>body</html>"

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            captured["transport"] = kwargs.get("transport")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, method, url, headers=None):
            return _FakeResp()

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    integrations._FETCH_CACHE.clear()
    out, _sources = integrations.web_fetch("https://example.test/x")

    assert isinstance(captured["transport"], egress._PinnedHTTPTransport)
    assert out.startswith("Fetched")


def test_web_fetch_port_tightening_rejects_non_standard_port(monkeypatch):
    # assert_public_url enforces the 80/443 port allowlist (OCD_EGRESS_ALLOW_PORTS).
    # A public IP is supplied so only the port rule can be the thing that triggers.
    _dns_sequence(monkeypatch, "8.8.8.8")
    integrations._FETCH_CACHE.clear()
    out, sources = integrations.web_fetch("https://example.com:8443/x")

    assert "url_not_allowed" in out
    assert sources == []


# ---------------------------------------------------------------------------
# web_search / DDG: fixed public host, routed through the pinned client for
# defense-in-depth + a single outbound chokepoint.
# ---------------------------------------------------------------------------


def test_ddg_uses_the_pinned_client(monkeypatch):
    captured = {}

    class _FakeResp:
        text = "<html></html>"

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            captured["transport"] = kwargs.get("transport")
            captured["follow_redirects"] = kwargs.get("follow_redirects")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, url, data=None, headers=None):
            captured["url"] = url
            return _FakeResp()

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    out = integrations._ddg_html_results("hello world", 5)

    assert out == []  # empty HTML parses to no results, but no exception either
    assert isinstance(captured["transport"], egress._PinnedHTTPTransport)
    assert captured["follow_redirects"] is False
    assert captured["url"] == integrations._DDG_URL


# ---------------------------------------------------------------------------
# web_search / SearXNG: base_url is TRUSTED CONFIG (a user setting), not
# agent-controlled -- must NOT be routed through the pinned client / assert_public_url,
# or a legitimate loopback self-host (Option-A) would break. Only redirects
# (driven by the agent-controlled query) are disabled.
# ---------------------------------------------------------------------------


def test_searxng_preserves_local_self_host_and_disables_redirects(monkeypatch):
    captured = {}

    class _FakeResp:
        def json(self):
            return {"results": []}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            captured["transport"] = kwargs.get("transport")
            captured["follow_redirects"] = kwargs.get("follow_redirects")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None, headers=None):
            captured["url"] = url
            return _FakeResp()

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    # No DNS/network monkeypatch at all: if this routed through assert_public_url or
    # pinned_client's transport in any resolving way, a loopback base would be a prime
    # candidate for rejection. Proving it ISN'T touched is the point of the test.
    results = integrations._searxng_results("q", 5, "http://127.0.0.1:8888")

    assert results == []  # reached the (stubbed) network and parsed fine -- not blocked
    assert "127.0.0.1:8888" in captured["url"]
    assert captured["follow_redirects"] is False
    # Never wrapped in the pinned transport -- plain client, trusted config exception.
    assert not isinstance(captured.get("transport"), egress._PinnedHTTPTransport)


# ---------------------------------------------------------------------------
# web_fetch error categorization: a DNS lookup FAILURE (transient / genuinely
# unreachable) must read as url_not_accessible, not url_not_allowed. egress
# raises EgressUnavailable (a subclass of EgressBlocked) for lookup failures so
# the pin's fail-closed handlers still catch it, but web_fetch can tell a
# transiently-down legitimate site apart from a real policy block.
# ---------------------------------------------------------------------------


def test_web_fetch_dns_failure_reads_as_unreachable_not_blocked(monkeypatch):
    def failing_getaddrinfo(*args, **kwargs):
        raise OSError("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", failing_getaddrinfo)
    integrations._FETCH_CACHE.clear()
    out, sources = integrations.web_fetch("https://example.com/x")

    assert "url_not_accessible" in out       # unreachable, not forbidden
    assert "url_not_allowed" not in out
    assert sources == []


# ---------------------------------------------------------------------------
# Redirect-approval (F2): first-contact domain approval OK's the INITIAL host;
# web_fetch is handed the project's approved-host set and must refuse a redirect
# to a host NOT in it (rather than follow it silently). approved_hosts=None
# (direct/non-agent callers) leaves redirect-approval off. SSRF + pinning still
# apply on every hop regardless.
# ---------------------------------------------------------------------------


class _RedirectResp:
    def __init__(self, status, headers, body=b""):
        self.status_code = status
        self.headers = headers
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_bytes(self):
        yield self._body


def _fake_redirect_client(monkeypatch, route):
    """Install a fake pinned_client whose stream() delegates to route(url), plus
    a no-op assert_public_url so the test exercises only redirect-approval."""
    monkeypatch.setattr(egress, "assert_public_url", lambda u, **k: u)

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, method, url, headers=None):
            return route(url)

    monkeypatch.setattr(egress, "pinned_client", lambda **k: _Client())


def test_web_fetch_refuses_redirect_to_an_unapproved_host(monkeypatch):
    def route(url):
        if "good.example" in url:
            return _RedirectResp(302, {"location": "https://evil.example/collect?data=secret"})
        return _RedirectResp(200, {"content-type": "text/html"}, b"<html>x</html>")

    _fake_redirect_client(monkeypatch, route)
    integrations._FETCH_CACHE.clear()
    out, sources = integrations.web_fetch("https://good.example/x", {"good.example"})
    assert "redirect_to_unapproved_host" in out
    assert "evil.example" in out        # names the host so the agent can re-fetch/re-gate
    assert sources == []


def test_web_fetch_follows_redirect_to_another_approved_host(monkeypatch):
    def route(url):
        if "good.example" in url:
            return _RedirectResp(302, {"location": "https://cdn.example/asset"})
        return _RedirectResp(200, {"content-type": "text/html"}, b"<html><title>Y</title>ok</html>")

    _fake_redirect_client(monkeypatch, route)
    integrations._FETCH_CACHE.clear()
    out, _ = integrations.web_fetch("https://good.example/x", {"good.example", "cdn.example"})
    assert out.startswith("Fetched")


def test_web_fetch_allows_same_host_redirect(monkeypatch):
    def route(url):
        if url.endswith("/x"):
            return _RedirectResp(302, {"location": "https://good.example/final"})
        return _RedirectResp(200, {"content-type": "text/html"}, b"<html>ok</html>")

    _fake_redirect_client(monkeypatch, route)
    integrations._FETCH_CACHE.clear()
    out, _ = integrations.web_fetch("https://good.example/x", {"good.example"})
    assert out.startswith("Fetched")


def test_web_fetch_without_approval_context_still_follows_redirects(monkeypatch):
    def route(url):
        if "good.example" in url:
            return _RedirectResp(302, {"location": "https://other.example/p"})
        return _RedirectResp(200, {"content-type": "text/html"}, b"<html>ok</html>")

    _fake_redirect_client(monkeypatch, route)
    integrations._FETCH_CACHE.clear()
    out, _ = integrations.web_fetch("https://good.example/x")  # approved_hosts=None
    assert out.startswith("Fetched")     # redirect-approval off -> followed
