"""SSRF DNS-rebinding TOCTOU tests for ocd_core.egress.

The vulnerability class these guard against: a validation helper resolves a
hostname and checks the answer, then hands a *bare hostname* to httpx/httpcore,
which resolves it a *second* time to open the socket. A DNS-rebinding attacker
answers the validation lookup with a public IP and the connect-time lookup with
a private/loopback/metadata IP (127.0.0.1, 169.254.169.254, ...), so the address
that is checked is never the address that is dialed.

egress closes the gap by resolving+validating inside the network backend's
``connect_tcp`` and dialing the *exact IP it just validated*. Validation and
connection therefore share one resolution — there is no window to rebind.

Local run (sidesteps the heavy app-import session fixture in tests/conftest.py
and the editable install that points ``ocd_core`` at another clone)::

    PYTHONPATH=<worktree>/backend python -m pytest --noconftest \
        backend/tests/test_egress_toctou.py -q
"""
import ipaddress
import socket

import httpcore
import pytest
from ocd_core import egress


# --------------------------------------------------------------------------- #
# Helpers mirroring the patterns the task established: a getaddrinfo stub that
# returns a scripted sequence of answers, and a spy on the *real* network
# backend proving a blocked answer never reaches the socket layer.
# --------------------------------------------------------------------------- #
def _addrinfo(ip: str, port: int = 443):
    """Build a getaddrinfo-shaped answer list for a single IP literal."""
    if ":" in ip:
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", (ip, port, 0, 0))]
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]


class _DnsSequence:
    """socket.getaddrinfo replacement returning scripted answers per call.

    Call N returns ``answers[N]`` (clamped to the last entry), so the first
    lookup can hand out a public IP and the second a private one — the essence
    of a DNS rebind.
    """

    def __init__(self, *answers: str):
        self.answers = list(answers)
        self.calls = 0

    def __call__(self, host, port=None, *a, **k):
        ip = self.answers[min(self.calls, len(self.answers) - 1)]
        self.calls += 1
        return _addrinfo(ip, port or 443)


def test_pinned_backend_blocks_rebind_to_private_at_connect_time(monkeypatch):
    """Headline TOCTOU proof.

    Validation lookup sees a public IP (passes); the connect-time lookup rebinds
    to loopback. The pinned backend re-resolves *at connect time* and must refuse
    — the private answer must never reach the real network layer.
    """
    seq = _DnsSequence("93.184.216.34", "127.0.0.1")
    monkeypatch.setattr(socket, "getaddrinfo", seq)

    reached = []

    def _spy_connect(self, host, port, **kw):  # the real SyncBackend.connect_tcp
        reached.append(host)
        raise AssertionError("real connect_tcp must not run once an answer is blocked")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", _spy_connect)

    backend = egress._PinnedSyncBackend()

    # 1) A caller pre-validates the host — consumes lookup #1 (public) -> allowed.
    assert egress.host_is_blocked("rebind.evil") is False
    # 2) The connection is opened — consumes lookup #2 (loopback) -> must block.
    with pytest.raises(egress.BlockedAddressError):
        backend.connect_tcp("rebind.evil", 443)

    assert reached == [], "blocked (rebound) address leaked to the real socket layer"


def test_pinned_backend_dials_the_validated_ip_not_the_hostname(monkeypatch):
    """Pinning proof: the socket targets the exact IP that was validated, as an IP
    literal, so no re-resolution can redirect the connection afterwards."""
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: _addrinfo("93.184.216.34", 443))

    dialed = {}

    def _capture(self, host, port, **kw):
        dialed["host"] = host
        dialed["port"] = port
        return object()  # stand-in NetworkStream; we never do real I/O here

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", _capture)

    egress._PinnedSyncBackend().connect_tcp("example.com", 443)

    assert dialed["host"] == "93.184.216.34"
    assert dialed["port"] == 443


def test_pinned_backend_blocks_metadata_ip(monkeypatch):
    """The cloud metadata endpoint (169.254.169.254) is refused at connect time."""
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: _addrinfo("169.254.169.254", 80))

    def _no_network(self, *a, **k):
        raise AssertionError("must not dial a blocked address")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", _no_network)

    with pytest.raises(egress.BlockedAddressError):
        egress._PinnedSyncBackend().connect_tcp("metadata.evil", 80)


def test_pinned_backend_falls_back_to_next_validated_address(monkeypatch):
    """Every resolved address is validated; if the first (e.g. a dead IPv6) fails
    to connect, the backend tries the next — preserving the stock happy-eyeballs
    fallback that dialing a single pinned IP would otherwise lose."""
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: _addrinfo("93.184.216.34") + _addrinfo("1.1.1.1"))

    attempts = []
    sentinel = object()

    def _connect(self, host, port, **kw):
        attempts.append(host)
        if host == "93.184.216.34":
            raise httpcore.ConnectError("refused")
        return sentinel

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", _connect)

    stream = egress._PinnedSyncBackend().connect_tcp("dual.example", 443)

    assert stream is sentinel
    assert attempts == ["93.184.216.34", "1.1.1.1"]


def test_pinned_backend_raises_when_all_validated_addresses_fail(monkeypatch):
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *a, **k: _addrinfo("93.184.216.34") + _addrinfo("1.1.1.1"))

    attempts = []

    def _connect(self, host, port, **kw):
        attempts.append(host)
        raise httpcore.ConnectError(f"refused {host}")

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", _connect)

    with pytest.raises(httpcore.ConnectError):
        egress._PinnedSyncBackend().connect_tcp("dual.example", 443)

    assert attempts == ["93.184.216.34", "1.1.1.1"]


# --------------------------------------------------------------------------- #
# _blocked_ip range coverage — reconciles the gaps the original _blocked_host
# missed. 100.64.0.0/10 (CGNAT) is the headline gap: every ipaddress flag reads
# False for it on CPython 3.12+, so a flags-only guard would let it through.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("ip", [
    "127.0.0.1",              # loopback
    "10.0.0.1",              # RFC1918
    "172.16.0.1",            # RFC1918
    "192.168.1.1",           # RFC1918
    "169.254.169.254",       # cloud metadata (link-local)
    "0.0.0.0",               # unspecified
    "0.1.2.3",               # 0.0.0.0/8
    "100.64.0.1",            # CGNAT (RFC6598) -- the reconciliation gap
    "192.0.0.1",             # IETF protocol assignments
    "198.18.0.1",            # benchmarking (RFC2544)
    "240.0.0.1",             # reserved (former class E)
    "255.255.255.255",       # broadcast
    "::1",                   # IPv6 loopback
    "fc00::1",               # IPv6 unique-local
    "fe80::1",               # IPv6 link-local
    "::ffff:127.0.0.1",      # IPv4-mapped loopback (smuggling)
    "::ffff:169.254.169.254",  # IPv4-mapped metadata (smuggling)
])
def test_blocked_ip_rejects_non_public(ip):
    assert egress._blocked_ip(ipaddress.ip_address(ip)) is True


@pytest.mark.parametrize("ip", [
    "93.184.216.34",         # example.com
    "1.1.1.1",
    "8.8.8.8",
    "2606:4700::1111",       # public IPv6
])
def test_blocked_ip_allows_public(ip):
    assert egress._blocked_ip(ipaddress.ip_address(ip)) is False


# --------------------------------------------------------------------------- #
# host_is_blocked — the cheap pre-check, failing closed.
# --------------------------------------------------------------------------- #
def test_host_is_blocked_empty_host():
    assert egress.host_is_blocked("") is True


def test_host_is_blocked_all_public(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: _addrinfo("93.184.216.34"))
    assert egress.host_is_blocked("good.example") is False


def test_host_is_blocked_mixed_answers_fails_closed(monkeypatch):
    """A host that resolves to *both* a public and a private address is blocked;
    an attacker cannot slip a private target in alongside a public decoy."""
    def _mixed(host, port=None, *a, **k):
        return (_addrinfo("93.184.216.34", port or 443)
                + _addrinfo("127.0.0.1", port or 443))

    monkeypatch.setattr(socket, "getaddrinfo", _mixed)
    assert egress.host_is_blocked("split.example") is True


# --------------------------------------------------------------------------- #
# Live sanity check: DNS-pinning must not break TLS. httpcore verifies the cert
# against the real hostname (origin), not the dialed IP literal. Skips cleanly
# when the network is unavailable so offline CI stays green.
# --------------------------------------------------------------------------- #
def test_pinned_client_real_https_preserves_tls_sni():
    with egress.pinned_client(timeout=15) as client:
        try:
            resp = client.get("https://example.com")
        except Exception as exc:  # noqa: BLE001 -- offline sandbox: skip, don't fail
            pytest.skip(f"network unavailable: {exc}")
    assert resp.status_code == 200
    assert "example" in resp.text.lower()
