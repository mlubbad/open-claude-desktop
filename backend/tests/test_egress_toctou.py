"""Close the DNS-rebinding TOCTOU: `assert_public_url` resolves the host once to
validate it, but until this fix `safe_get`/`mcp_httpx_client_factory` handed the
*URL* to httpx, which re-resolved the hostname independently to open the socket.
A rebinding attacker can answer PUBLIC during validation and PRIVATE (or a
metadata IP) during connect, since the two resolutions are unrelated.

The fix pins the connection: the pinned backend resolves+validates the host
itself, at actual connect time, and dials only the address it just checked --
so the address that is checked is always the address that is used.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket

import httpcore
import httpx
import pytest
from ocd_core import egress


def _dns_sequence(monkeypatch, *answers: str):
    """Each successive call to socket.getaddrinfo returns the next address in
    `answers` (repeating the last one once exhausted). This lets a test give
    `assert_public_url`'s pre-flight lookup a different answer than the
    pinned backend's own connect-time lookup -- simulating a rebind.
    """
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
# _resolve_ips: the single connect-time resolution helper
# ---------------------------------------------------------------------------


def test_resolve_ips_returns_validated_public_addresses(monkeypatch):
    _dns_sequence(monkeypatch, "8.8.8.8")
    assert egress._resolve_ips("example.test", 443) == ["8.8.8.8"]


def test_resolve_ips_blocks_private_answers(monkeypatch):
    _dns_sequence(monkeypatch, "127.0.0.1")
    with pytest.raises(egress.EgressBlocked):
        egress._resolve_ips("attacker.test", 443)


# ---------------------------------------------------------------------------
# Blocked-at-connect: the pinned backend rejects a private resolution on its
# OWN, independent of assert_public_url ever having been called.
# ---------------------------------------------------------------------------


def test_pinned_sync_backend_blocks_connect_to_private_ip(monkeypatch):
    _dns_sequence(monkeypatch, "127.0.0.1")
    backend = egress._PinnedSyncBackend()
    with pytest.raises(egress.EgressBlocked):
        backend.connect_tcp("attacker.test", 443)


def test_pinned_async_backend_blocks_connect_to_private_ip(monkeypatch):
    _dns_sequence(monkeypatch, "169.254.169.254")
    backend = egress._PinnedAsyncBackend()

    async def run():
        with pytest.raises(egress.EgressBlocked):
            await backend.connect_tcp("attacker.test", 443)

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Proof of pinning: the real network layer is called with the RESOLVED IP,
# never the hostname -- so there is no second, independent lookup for an
# attacker to race.
# ---------------------------------------------------------------------------


def test_pinned_sync_backend_dials_the_resolved_ip_not_the_hostname(monkeypatch):
    _dns_sequence(monkeypatch, "8.8.8.8")
    seen = {}

    def fake_connect_tcp(self, host, port, **kwargs):
        seen["host"] = host
        seen["port"] = port
        raise httpcore.ConnectError("stubbed -- no real network in unit tests")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", fake_connect_tcp)

    backend = egress._PinnedSyncBackend()
    with pytest.raises(httpcore.ConnectError):
        backend.connect_tcp("example.test", 443)

    assert seen == {"host": "8.8.8.8", "port": 443}


def test_pinned_async_backend_dials_the_resolved_ip_not_the_hostname(monkeypatch):
    _dns_sequence(monkeypatch, "8.8.8.8")
    seen = {}

    async def fake_connect_tcp(self, host, port, **kwargs):
        seen["host"] = host
        seen["port"] = port
        raise httpcore.ConnectError("stubbed -- no real network in unit tests")

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", fake_connect_tcp)

    backend = egress._PinnedAsyncBackend()

    async def run():
        with pytest.raises(httpcore.ConnectError):
            await backend.connect_tcp("example.test", 443)

    asyncio.run(run())
    assert seen == {"host": "8.8.8.8", "port": 443}


# ---------------------------------------------------------------------------
# The rebind itself: assert_public_url's pre-flight check sees a PUBLIC
# answer; the real connect re-resolves independently and gets a PRIVATE
# answer. The private answer must never reach the real socket layer.
# ---------------------------------------------------------------------------


def test_rebind_between_validation_and_connect_is_blocked(monkeypatch):
    # 1st DNS answer -> safe_get's assert_public_url pre-flight check (passes).
    # 2nd DNS answer -> the pinned backend's own connect-time resolution
    # (the attacker "rebinds" to loopback right when the socket would open).
    _dns_sequence(monkeypatch, "8.8.8.8", "127.0.0.1")

    reached_real_network = []

    def spy_connect_tcp(self, host, *args, **kwargs):
        reached_real_network.append(host)
        raise AssertionError("must not reach the real network layer")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", spy_connect_tcp)

    with pytest.raises(egress.EgressBlocked):
        egress.safe_get("https://attacker.test/x")

    assert reached_real_network == []


def test_rebind_is_blocked_for_the_mcp_async_client(monkeypatch):
    _dns_sequence(monkeypatch, "8.8.8.8", "127.0.0.1")

    reached_real_network = []

    async def spy_connect_tcp(self, host, *args, **kwargs):
        reached_real_network.append(host)
        raise AssertionError("must not reach the real network layer")

    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", spy_connect_tcp)

    async def run():
        async with egress.mcp_httpx_client_factory() as client:
            with pytest.raises(egress.EgressBlocked):
                await client.get("https://attacker.test/x")

    asyncio.run(run())
    assert reached_real_network == []


# ---------------------------------------------------------------------------
# Clients use the pinned path.
# ---------------------------------------------------------------------------


def test_safe_get_uses_the_pinned_transport(monkeypatch):
    _dns_sequence(monkeypatch, "8.8.8.8")
    captured = {}

    class _FakeResponse:
        status_code = 200
        headers: dict = {}

    class _FakeClient:
        def __init__(self, *args, **kwargs):
            captured["transport"] = kwargs.get("transport")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            return _FakeResponse()

    monkeypatch.setattr(httpx, "Client", _FakeClient)
    egress.safe_get("https://example.test/x")

    assert isinstance(captured["transport"], egress._PinnedHTTPTransport)


def test_mcp_httpx_client_factory_uses_the_pinned_transport():
    client = egress.mcp_httpx_client_factory()
    assert isinstance(client._transport, egress._PinnedAsyncHTTPTransport)


# ---------------------------------------------------------------------------
# HTTPS still works: TLS verification must use the real hostname (for SNI and
# certificate-hostname checks) even though the socket connects to the pinned
# IP. Proven deterministically (no live network needed): the fake network
# layer records what `connect_tcp` and `start_tls` each receive, and they
# must differ -- the IP for the socket, the hostname for TLS.
# ---------------------------------------------------------------------------


def test_https_sni_and_verification_hostname_survive_ip_pinning(monkeypatch):
    _dns_sequence(monkeypatch, "8.8.8.8")
    seen_connect_host = {}
    seen_tls_hostname = {}

    class _FakeStream:
        def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            seen_tls_hostname["value"] = server_hostname
            raise httpcore.ConnectError("stubbed -- stop before any real I/O")

        def get_extra_info(self, info):
            return None

    def fake_connect_tcp(self, host, port, **kwargs):
        seen_connect_host["value"] = host
        return _FakeStream()

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", fake_connect_tcp)

    with pytest.raises(httpx.ConnectError):
        with httpx.Client(transport=egress._PinnedHTTPTransport()) as client:
            client.get("https://example.test/secure")

    assert seen_connect_host["value"] == "8.8.8.8"  # socket pinned to the resolved IP
    assert seen_tls_hostname["value"] == "example.test"  # TLS still verifies the real host


def test_https_to_a_real_public_host_completes_the_tls_handshake():
    """Best-effort live check, per the task's explicit allowance. Skips
    cleanly if this environment has no outbound network -- the deterministic
    test above already proves the SNI/hostname property without a network."""
    try:
        response = egress.safe_get("https://example.com/")
    except egress.EgressBlocked:
        raise
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"no outbound network available in this environment: {exc}")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Fail closed on unsupported pool configs. httpcore's HTTPProxy/SOCKSProxy
# pools subclass ConnectionPool, so the pinned transports must match the exact
# type -- an isinstance() check would let a proxy pool through and silently
# drop its config (serving an unpinned connection). A proxied transport must
# raise instead of quietly de-pinning itself.
# ---------------------------------------------------------------------------


def test_pinned_sync_transport_fails_closed_on_a_proxy_pool():
    with pytest.raises(egress.EgressBlocked):
        egress._PinnedHTTPTransport(proxy="http://127.0.0.1:9999")


def test_pinned_async_transport_fails_closed_on_a_proxy_pool():
    with pytest.raises(egress.EgressBlocked):
        egress._PinnedAsyncHTTPTransport(proxy="http://127.0.0.1:9999")


# ---------------------------------------------------------------------------
# IPv4-mapped IPv6 must not smuggle a custom-blocked v4 range past _blocked_ip.
# Python's own is_private/is_reserved don't flag CGNAT (100.64/10), so it's only
# caught by the custom _BLOCKED_V4 list -- which used to be gated on
# isinstance(addr, IPv4Address), skipping the ::ffff:x.x.x.x mapped form. A
# rebinding resolver could answer with ::ffff:100.64.0.1 to reach CGNAT space.
# ---------------------------------------------------------------------------


def test_blocked_ip_catches_ipv4_mapped_custom_v4_ranges():
    # CGNAT via its mapped form: the regression case.
    assert egress._blocked_ip(ipaddress.ip_address("::ffff:100.64.0.1")) is True
    assert egress._blocked_ip(ipaddress.ip_address("100.64.0.1")) is True
    # Loopback/metadata mapped forms stay blocked (were already, via built-ins).
    assert egress._blocked_ip(ipaddress.ip_address("::ffff:127.0.0.1")) is True
    assert egress._blocked_ip(ipaddress.ip_address("::ffff:169.254.169.254")) is True
    # A genuinely public address -- bare or mapped -- is still allowed.
    assert egress._blocked_ip(ipaddress.ip_address("::ffff:8.8.8.8")) is False
    assert egress._blocked_ip(ipaddress.ip_address("8.8.8.8")) is False
    assert egress._blocked_ip(ipaddress.ip_address("2001:4860:4860::8888")) is False


def test_resolve_ips_blocks_mapped_cgnat_rebind(monkeypatch):
    # End-to-end through the connect-time resolver: a ::ffff:100.64.x answer is
    # rejected, so the pinned transport never dials it.
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:100.64.0.1", 0, 0, 0))],
    )
    with pytest.raises(egress.EgressBlocked):
        egress._resolve_ips("attacker.test", 443)
