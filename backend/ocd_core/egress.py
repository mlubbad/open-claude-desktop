"""SSRF-safe outbound HTTP — DNS-pinned so validation and connection agree.

Naive SSRF guards resolve a hostname, check the answer, then hand the *bare
hostname* to httpx/httpcore, which resolves it a *second* time to open the
socket. A DNS-rebinding attacker answers the first lookup with a public IP and
the second with a private/loopback/metadata address, so the IP that was checked
is never the IP that is dialed (a classic TOCTOU).

This module closes that window: the pinned network backend resolves and
validates the host *inside* ``connect_tcp`` and then dials the exact IP literal
it just validated. There is a single resolution, shared by the check and the
connect, so there is nothing to rebind. TLS still verifies the real hostname —
httpcore derives ``server_hostname`` from the connection's origin, not from the
address ``connect_tcp`` was told to dial — so HTTPS/SNI is unaffected.

Public surface:
  * ``host_is_blocked(host)`` — resolve + validate; True if empty/unresolvable
    or any answer is non-public. Cheap pre-check for callers.
  * ``pinned_client(**kwargs)`` — an ``httpx.Client`` whose every connection is
    DNS-pinned and validated at connect time.
  * ``BlockedAddressError`` — raised (as an ``httpcore.ConnectError`` subclass,
    so httpx surfaces it as a connection failure) when an address is refused.
"""
from __future__ import annotations

import ipaddress
import socket
import typing

import httpcore
import httpx


class BlockedAddressError(httpcore.ConnectError):
    """A host resolved to a non-public address (or did not resolve at all).

    Subclasses ``httpcore.ConnectError`` so that when it is raised inside a
    pinned connection it propagates through httpx as an ``httpx.ConnectError``
    rather than an opaque 500-style crash.
    """


# IPv4 ranges that are NOT reliably flagged by ipaddress' is_private/is_reserved
# across CPython versions and must be blocked explicitly. Most notably CGNAT
# (100.64.0.0/10) reports every flag False on 3.12+ yet must never be reachable.
_EXTRA_BLOCKED_V4: tuple[ipaddress.IPv4Network, ...] = (
    ipaddress.ip_network("0.0.0.0/8"),        # "this host on this network"
    ipaddress.ip_network("100.64.0.0/10"),    # CGNAT (RFC 6598)
    ipaddress.ip_network("192.0.0.0/24"),     # IETF protocol assignments
    ipaddress.ip_network("198.18.0.0/15"),    # benchmarking (RFC 2544)
    ipaddress.ip_network("240.0.0.0/4"),      # reserved (former class E)
)


def _blocked_ip(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True if ``addr`` is anything other than a public, globally-routable host.

    Belt-and-suspenders: the standard flags, the explicit extra ranges above,
    and a final ``not is_global`` backstop. IPv4-mapped IPv6 (``::ffff:a.b.c.d``)
    is normalized to its IPv4 form first so it cannot smuggle a private target.
    """
    mapped = getattr(addr, "ipv4_mapped", None)
    if mapped is not None:
        addr = mapped
    if (addr.is_private or addr.is_loopback or addr.is_link_local
            or addr.is_reserved or addr.is_multicast or addr.is_unspecified):
        return True
    if addr.version == 4:
        for net in _EXTRA_BLOCKED_V4:
            if addr in net:
                return True
    if not addr.is_global:
        return True
    return False


def resolve_and_validate(
    host: str, port: int | None,
) -> list[tuple]:
    """Resolve ``host`` and validate *every* answer.

    Returns the getaddrinfo entries (all validated public addresses) or raises
    ``BlockedAddressError`` if the host is empty, does not resolve, or *any*
    answer is non-public. Failing closed on a mixed answer set matches the
    conservative posture of the original ``_blocked_host``.
    """
    if not host:
        raise BlockedAddressError("empty host")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise BlockedAddressError(f"cannot resolve host {host!r}") from exc
    if not infos:
        raise BlockedAddressError(f"host {host!r} did not resolve")
    for info in infos:
        raw = info[4][0].split("%")[0]
        try:
            addr = ipaddress.ip_address(raw)
        except ValueError as exc:
            raise BlockedAddressError(f"unparseable address {raw!r}") from exc
        if _blocked_ip(addr):
            raise BlockedAddressError(f"blocked address {raw} for host {host!r}")
    return infos


def host_is_blocked(host: str) -> bool:
    """Cheap pre-check: True if ``host`` is empty, unresolvable, or resolves to
    any non-public address. Never raises."""
    try:
        resolve_and_validate(host, None)
    except BlockedAddressError:
        return True
    return False


class _PinnedSyncBackend(httpcore.SyncBackend):
    """A network backend that validates at connect time and dials the validated
    IP literal — so the checked address is exactly the dialed address."""

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: typing.Iterable[typing.Any] | None = None,
    ) -> httpcore.NetworkStream:
        infos = resolve_and_validate(host, port)
        # Dial the exact IPs we validated, as literals, so httpcore's own
        # getaddrinfo cannot re-resolve the name to a different (rebound) target.
        # Try each validated address in turn (like the stock happy-eyeballs
        # fallback) so a single dead address — e.g. an unreachable IPv6 on a
        # dual-stack host — doesn't sink the whole connection.
        last_exc: Exception | None = None
        for info in infos:
            ip = info[4][0].split("%")[0]
            try:
                return super().connect_tcp(
                    ip,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_exc = exc
        # Every validated address failed to connect. resolve_and_validate
        # guarantees at least one address, so last_exc is always set here.
        raise last_exc if last_exc is not None else BlockedAddressError(
            f"host {host!r} had no connectable address")


class _PinnedHTTPTransport(httpx.HTTPTransport):
    """``httpx.HTTPTransport`` whose connection pool uses the pinned backend."""

    def __init__(self, **kwargs: typing.Any) -> None:
        super().__init__(**kwargs)
        # httpx builds the pool with the default SyncBackend; swap in ours.
        self._pool._network_backend = _PinnedSyncBackend()


def pinned_client(**kwargs: typing.Any) -> httpx.Client:
    """An ``httpx.Client`` that DNS-pins and validates every connection.

    Passing an explicit transport also makes httpx route *all* requests through
    it, bypassing ambient ``HTTP(S)_PROXY`` env vars that would otherwise defeat
    the pin.
    """
    kwargs.setdefault("transport", _PinnedHTTPTransport())
    return httpx.Client(**kwargs)
