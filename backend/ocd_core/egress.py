"""Fail-closed outbound network policy for every user-controlled URL.

The policy validates the URL, hostname, configured domain policy, and every DNS
answer before a connection is attempted. Redirect-capable helpers re-run this
check for each hop. Long-lived protocol clients (MCP/OAuth) use an httpx request
hook, so discovery and redirected requests are checked too.
"""
from __future__ import annotations

import ipaddress
import os
import socket
from collections.abc import Iterable
from urllib.parse import urljoin, urlsplit

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
            raise EgressBlocked(f"destination DNS lookup failed: {host}") from exc
        addresses = {ipaddress.ip_address(answer[4][0].split("%")[0]) for answer in answers}
        if not addresses:
            raise EgressBlocked(f"destination DNS lookup returned no addresses: {host}")
        return addresses
    return {literal}


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


def safe_get(
    url: str,
    *,
    headers: dict | None = None,
    timeout: float = 15,
    max_redirects: int = 4,
    sensitive_headers: Iterable[str] = (),
):
    """Perform an SSRF-safe GET, validating every redirect before connecting."""
    import httpx

    current = assert_public_url(url)
    current_headers = dict(headers or {})
    protected_headers = _SENSITIVE_HEADERS | {
        header.lower() for header in sensitive_headers if header
    }
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
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
    import httpx

    async def validate(request: httpx.Request) -> None:
        assert_public_url(str(request.url))

    return httpx.AsyncClient(
        headers=headers,
        timeout=timeout,
        auth=auth,
        follow_redirects=False,
        event_hooks={"request": [validate]},
    )
