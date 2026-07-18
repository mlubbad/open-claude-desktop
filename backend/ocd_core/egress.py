"""Fail-closed outbound network policy for every user-controlled URL.

The policy validates the URL, hostname, configured domain policy, and every DNS
answer before a connection is attempted. Redirect-capable helpers re-run this
check for each hop. Long-lived protocol clients (MCP/OAuth) use an httpx request
hook, so discovery and redirected requests are checked too.

Validating a hostname and opening a socket to it are two different DNS
lookups unless something pins them together. A DNS-rebinding attacker can
answer with a public address for the first (the validation) and a private or
metadata address for the second (the actual connect), which would otherwise
sail straight through. `_PinnedSyncBackend`/`_PinnedAsyncBackend` close that
gap: they do their own resolve-and-validate at the moment a socket is about
to open, and connect only to the address they just checked -- so `safe_get`
and `mcp_httpx_client_factory` never hand httpx a bare hostname to re-resolve
on its own.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Iterable
from urllib.parse import urljoin, urlsplit

import anyio
import httpcore
import httpx

_BLOCKED_V4 = (
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("192.0.0.0/24"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("224.0.0.0/4"),
    ipaddress.ip_network("240.0.0.0/4"),
)
_LOCAL_SUFFIXES = (".localhost", ".local", ".internal", ".home", ".lan")
_SENSITIVE_HEADERS = {
    "authorization",
    "proxy-authorization",
    "cookie",
    "x-api-key",
    "api-key",
}


class EgressBlocked(ValueError):
    """The destination violates the configured outbound policy."""


class EgressUnavailable(EgressBlocked):
    """The destination could not be resolved/reached (a transient or network
    failure), as opposed to being refused by policy. Subclasses EgressBlocked
    so every existing fail-closed ``except EgressBlocked`` handler still catches
    it; callers that want to distinguish "couldn't reach it" from "policy says
    no" (e.g. web_fetch's error messaging) catch this first."""


def _domains(env_name: str) -> tuple[str, ...]:
    return tuple(
        value.strip().lower().rstrip(".")
        for value in os.getenv(env_name, "").split(",")
        if value.strip()
    )


def _domain_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith(f".{domain}")


def _blocked_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        return True
    return isinstance(address, ipaddress.IPv4Address) and any(
        address in network for network in _BLOCKED_V4
    )


def _resolved_addresses(host: str, port: int) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        try:
            answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise EgressUnavailable(f"destination DNS lookup failed: {host}") from exc
        addresses = {ipaddress.ip_address(answer[4][0].split("%")[0]) for answer in answers}
        if not addresses:
            raise EgressUnavailable(f"destination DNS lookup returned no addresses: {host}") from None
        return addresses
    return {literal}


def _resolve_ips(host: str, port: int) -> list[str]:
    """Resolve *host* and return every answer as a validated IP string.

    This is the resolution the pinned transport actually connects to. It runs
    again at connect time and does not reuse or cache whatever
    `assert_public_url` saw earlier, so a rebinding resolver that flips its
    answer between "validate" and "connect" is caught right here -- this is
    the only resolution whose result ever reaches a socket.
    """
    addresses = _resolved_addresses(host, port)
    if any(_blocked_ip(address) for address in addresses):
        raise EgressBlocked("destination resolves to a private or non-routable address")
    if not addresses:  # pragma: no cover - _resolved_addresses already guards this
        raise EgressBlocked(f"destination DNS lookup returned no addresses: {host}")
    return [str(address) for address in addresses]


def assert_public_url(url: str, *, schemes: Iterable[str] = ("https", "http")) -> str:
    """Validate and return a normalized user-controlled network URL."""
    candidate = (url or "").strip()
    try:
        parsed = urlsplit(candidate)
        port = parsed.port
    except ValueError as exc:
        raise EgressBlocked("invalid destination URL") from exc
    allowed_schemes = {scheme.lower() for scheme in schemes}
    if parsed.scheme.lower() not in allowed_schemes or not parsed.hostname:
        raise EgressBlocked(
            f"destination must use one of: {', '.join(sorted(allowed_schemes))}"
        )
    if parsed.username is not None or parsed.password is not None:
        raise EgressBlocked("credentials in destination URLs are not allowed")

    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(_LOCAL_SUFFIXES):
        raise EgressBlocked("local and internal hostnames are blocked")
    denied = _domains("OCD_EGRESS_DENY_DOMAINS")
    if any(_domain_matches(host, domain) for domain in denied):
        raise EgressBlocked("destination domain is denied by policy")
    allowed = _domains("OCD_EGRESS_ALLOW_DOMAINS")
    if allowed and not any(_domain_matches(host, domain) for domain in allowed):
        raise EgressBlocked("destination domain is not in the egress allowlist")

    effective_port = port or (443 if parsed.scheme.lower() == "https" else 80)
    permitted_ports = {
        int(value)
        for value in os.getenv("OCD_EGRESS_ALLOW_PORTS", "80,443").split(",")
        if value.strip().isdigit()
    }
    if effective_port not in permitted_ports:
        raise EgressBlocked(f"destination port {effective_port} is blocked")
    addresses = _resolved_addresses(host, effective_port)
    if any(_blocked_ip(address) for address in addresses):
        raise EgressBlocked("destination resolves to a private or non-routable address")
    return candidate


class _PinnedSyncBackend(httpcore.SyncBackend):
    """A `SyncBackend` that resolves and validates the host itself, then
    connects only to the address it just checked. `connect_tcp` receives the
    hostname (httpcore's own resolution never runs), so pinning here is what
    keeps "the address that was validated" and "the address that gets
    connected to" the same address, every time."""

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ):
        last_error: Exception | None = None
        for ip in _resolve_ips(host, port):
            try:
                return super().connect_tcp(
                    ip,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        if last_error is None:  # pragma: no cover - _resolve_ips never returns an empty list
            raise EgressBlocked("destination could not be connected to")
        raise last_error


class _PinnedAsyncBackend(httpcore.AnyIOBackend):
    """Async counterpart of `_PinnedSyncBackend`."""

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ):
        # _resolve_ips runs a blocking getaddrinfo; keep it off the event loop
        # so a slow or hostile resolver stalls only this connect, not every
        # other request sharing the loop.
        ips = await anyio.to_thread.run_sync(_resolve_ips, host, port)
        last_error: Exception | None = None
        for ip in ips:
            try:
                return await super().connect_tcp(
                    ip,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        if last_error is None:  # pragma: no cover - _resolve_ips never returns an empty list
            raise EgressBlocked("destination could not be connected to")
        raise last_error


def _pinned_pool_kwargs(pool) -> dict:
    """Copy the config httpx already built into `pool` (its ssl_context,
    limits, ...) so the pinned pool we swap in behaves identically except for
    the network backend."""
    return {
        "ssl_context": pool._ssl_context,
        "max_connections": pool._max_connections,
        "max_keepalive_connections": pool._max_keepalive_connections,
        "keepalive_expiry": pool._keepalive_expiry,
        "http1": pool._http1,
        "http2": pool._http2,
        "retries": pool._retries,
        "local_address": pool._local_address,
        "uds": pool._uds,
        "socket_options": pool._socket_options,
    }


class _PinnedHTTPTransport(httpx.HTTPTransport):
    """`HTTPTransport` whose connection pool is pinned: every socket opens
    only to an address `_resolve_ips` validated moments before, closing the
    gap between `assert_public_url`'s check and httpx's own DNS lookup."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        pool = self._pool
        # httpcore's HTTPProxy/SOCKSProxy pools subclass ConnectionPool, so an
        # isinstance() check would pass them through and _pinned_pool_kwargs
        # would silently drop their proxy config. Match the exact type and fail
        # closed on anything else rather than serve an unpinned connection.
        if type(pool) is not httpcore.ConnectionPool:
            raise EgressBlocked(
                "pinned transport does not support this transport configuration"
            )
        self._pool = httpcore.ConnectionPool(
            network_backend=_PinnedSyncBackend(), **_pinned_pool_kwargs(pool)
        )


class _PinnedAsyncHTTPTransport(httpx.AsyncHTTPTransport):
    """Async counterpart of `_PinnedHTTPTransport`."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        pool = self._pool
        # See _PinnedHTTPTransport: match the exact pool type so proxy pools
        # (ConnectionPool subclasses) fail closed instead of losing their config.
        if type(pool) is not httpcore.AsyncConnectionPool:
            raise EgressBlocked(
                "pinned transport does not support this transport configuration"
            )
        self._pool = httpcore.AsyncConnectionPool(
            network_backend=_PinnedAsyncBackend(), **_pinned_pool_kwargs(pool)
        )


def pinned_client(**kwargs) -> httpx.Client:
    """An httpx.Client whose sockets are DNS-pinned to a validated public IP
    (see _PinnedHTTPTransport). Use for agent-triggered outbound HTTP so a
    rebinding resolver can't swing the connection to a private/metadata address
    between validation and connect.

    Rejects ``proxy``/``mounts``: httpx mounts those as separate, *unpinned*
    transports that would silently bypass the pin for matching requests."""
    if "proxy" in kwargs or "mounts" in kwargs:
        raise EgressBlocked(
            "pinned_client does not support proxy/mounts (they would bypass the DNS pin)"
        )
    return httpx.Client(transport=_PinnedHTTPTransport(), **kwargs)


def safe_get(
    url: str,
    *,
    headers: dict | None = None,
    timeout: float = 15,
    max_redirects: int = 4,
    sensitive_headers: Iterable[str] = (),
):
    """Perform an SSRF-safe GET, validating every redirect before connecting."""
    current = assert_public_url(url)
    current_headers = dict(headers or {})
    protected_headers = _SENSITIVE_HEADERS | {
        header.lower() for header in sensitive_headers if header
    }
    with httpx.Client(
        timeout=timeout, follow_redirects=False, transport=_PinnedHTTPTransport()
    ) as client:
        for _ in range(max_redirects + 1):
            response = client.get(current, headers=current_headers)
            location = response.headers.get("location")
            if response.status_code in (301, 302, 303, 307, 308) and location:
                target = assert_public_url(urljoin(current, location))
                old = urlsplit(current)
                new = urlsplit(target)
                if (old.scheme, old.hostname, old.port) != (
                    new.scheme,
                    new.hostname,
                    new.port,
                ):
                    current_headers = {
                        key: value
                        for key, value in current_headers.items()
                        if key.lower() not in protected_headers
                    }
                current = target
                continue
            return response
    raise EgressBlocked("too many outbound redirects")


def mcp_httpx_client_factory(headers=None, timeout=None, auth=None):
    """Build an MCP/OAuth client that checks every request and rejects redirects.

    Remote protocol redirects are intentionally fail-closed: accepting them would
    either risk credential forwarding or require protocol-specific origin rules.
    Operators should configure the canonical MCP endpoint URL instead.
    """

    async def validate(request: httpx.Request) -> None:
        assert_public_url(str(request.url))

    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        follow_redirects=False,
        event_hooks={"request": [validate]},
        transport=_PinnedAsyncHTTPTransport(),
    )
