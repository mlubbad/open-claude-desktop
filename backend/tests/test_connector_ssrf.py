"""End-to-end SSRF tests for integrations.web_fetch.

egress.py proves the DNS-pinned backend in isolation; these prove web_fetch is
actually wired through it — the rebind is blocked end to end, and the reconciled
IP-range policy (CGNAT, metadata, loopback, ...) is enforced at the pre-check.

Local run (skips the heavy app-import session fixture in tests/conftest.py and
the editable install that points ``ocd_core`` at another clone)::

    PYTHONPATH=<worktree>/backend python -m pytest --noconftest \
        backend/tests/test_connector_ssrf.py -q
"""
import socket

import httpcore
import httpx
import pytest
from ocd_core import integrations


def _addrinfo(ip: str, port: int = 443):
    if ":" in ip:
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, port, 0, 0))]
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]


class _DnsSequence:
    """getaddrinfo returning a public IP on the first lookup and a private one on
    the second — a DNS rebind between the pre-check and the socket connect."""

    def __init__(self, *answers: str):
        self.answers = list(answers)
        self.calls = 0

    def __call__(self, host, port=None, *a, **k):
        ip = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return _addrinfo(ip, port or 443)


def test_web_fetch_blocks_dns_rebind_to_private(monkeypatch):
    """Headline: the pre-check sees a public IP, the connect-time lookup rebinds
    to loopback. web_fetch must fail without the private address ever reaching
    the real socket layer."""
    monkeypatch.setattr(socket, "getaddrinfo",
                        _DnsSequence("93.184.216.34", "127.0.0.1"))

    reached = []

    def _spy_connect(self, host, port, **kw):  # real SyncBackend.connect_tcp
        reached.append(host)
        raise AssertionError("blocked/rebound address reached the real socket layer")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", _spy_connect)

    out, src = integrations.web_fetch("http://rebind.evil/path")

    assert out.startswith("web_fetch_tool_error")
    assert src == []
    assert reached == [], "web_fetch dialed the rebound private address"


def test_web_fetch_blocks_loopback_literal():
    out, src = integrations.web_fetch("http://127.0.0.1/")
    assert out.startswith("web_fetch_tool_error: url_not_allowed")
    assert src == []


def test_web_fetch_blocks_cgnat_literal():
    """100.64.0.0/10 (CGNAT) — the range the original flag-only _blocked_host let
    through. Reconciled via egress._blocked_ip."""
    out, src = integrations.web_fetch("http://100.64.0.1/")
    assert out.startswith("web_fetch_tool_error: url_not_allowed")
    assert src == []


def test_web_fetch_blocks_metadata_literal():
    out, src = integrations.web_fetch("http://169.254.169.254/latest/meta-data/")
    assert out.startswith("web_fetch_tool_error: url_not_allowed")


def test_web_fetch_rejects_non_http_scheme():
    out, _ = integrations.web_fetch("ftp://example.com/resource")
    assert out.startswith("web_fetch_tool_error: invalid_input")


def test_web_fetch_rejects_empty_url():
    out, _ = integrations.web_fetch("   ")
    assert out.startswith("web_fetch_tool_error: invalid_input")


# --------------------------------------------------------------------------- #
# REST connector fetches (_http_get / test_connector / call_connector).
# Same DNS-pinned egress guard as web_fetch, but with a per-connector
# `allow_private` opt-in so a user can point a connector at their own internal
# API on purpose. Default (flag absent/False) blocks private/internal hosts.
# --------------------------------------------------------------------------- #
class _Dialed(Exception):
    """Sentinel raised by the connect spy to halt before any real socket I/O
    while recording that a dial was attempted (i.e. the host was *allowed*)."""


def test_http_get_blocks_private_host_by_default(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: _addrinfo("127.0.0.1", 80))
    reached = []

    def _spy(self, host, port, **kw):
        reached.append(host)
        raise AssertionError("blocked host reached the real socket layer")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", _spy)

    with pytest.raises(httpx.ConnectError):
        integrations._http_get("http://internal.local/", {"User-Agent": "x"})

    assert reached == []


def test_http_get_allow_private_permits_private_host(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: _addrinfo("127.0.0.1", 80))
    dialed = []

    def _capture(self, host, port, **kw):
        dialed.append(host)
        raise _Dialed()

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", _capture)

    with pytest.raises(_Dialed):
        integrations._http_get("http://internal.local/", {}, allow_private=True)

    assert dialed == ["internal.local"]  # plain path: no block, no pin


def test_call_connector_blocks_private_base_url(monkeypatch):
    monkeypatch.setattr(
        integrations, "_load_user_connectors",
        lambda: [{"id": "c1", "name": "C1", "base_url": "http://169.254.169.254"}])
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: _addrinfo("169.254.169.254", 80))
    reached = []

    def _spy(self, host, port, **kw):
        reached.append(host)
        raise AssertionError("blocked host reached the real socket layer")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", _spy)

    out = integrations.call_connector("c1", "/v1/data")

    assert out.startswith("Connector 'c1' request failed")
    assert reached == []


def test_call_connector_allow_private_permits(monkeypatch):
    monkeypatch.setattr(
        integrations, "_load_user_connectors",
        lambda: [{"id": "c1", "name": "C1", "base_url": "http://10.0.0.5",
                  "allow_private": True}])
    dialed = []

    def _capture(self, host, port, **kw):
        dialed.append(host)
        raise _Dialed()

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", _capture)

    integrations.call_connector("c1", "/x")

    assert dialed == ["10.0.0.5"]


def test_call_connector_non_bool_allow_private_does_not_bypass(monkeypatch):
    """A hand-edited connectors.json with a *truthy string* (e.g. "no") must not
    silently disable the SSRF guard — only a real True opts in."""
    monkeypatch.setattr(
        integrations, "_load_user_connectors",
        lambda: [{"id": "c1", "name": "C1", "base_url": "http://127.0.0.1",
                  "allow_private": "no"}])
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: _addrinfo("127.0.0.1", 80))
    reached = []

    def _spy(self, host, port, **kw):
        reached.append(host)
        raise AssertionError("blocked host reached the real socket layer")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", _spy)

    out = integrations.call_connector("c1", "/x")

    assert out.startswith("Connector 'c1' request failed")
    assert reached == []


def test_add_connector_persists_allow_private(monkeypatch):
    saved = {}
    monkeypatch.setattr(integrations, "_load_user_connectors",
                        lambda: saved.get("items", []))
    monkeypatch.setattr(integrations, "_save_user_connectors",
                        lambda items: saved.__setitem__("items", items))

    on = integrations.add_connector("Internal", "http://10.0.0.5", allow_private=True)
    assert on["allow_private"] is True
    assert saved["items"][-1]["allow_private"] is True

    off = integrations.add_connector("Public", "https://api.example.com")
    assert off["allow_private"] is False
