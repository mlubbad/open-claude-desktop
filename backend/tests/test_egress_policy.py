from __future__ import annotations

import socket

import pytest

from ocd_core import egress


def _dns(monkeypatch, *addresses: str):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))
            for address in addresses
        ],
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/x",
        "file:///etc/passwd",
        "https://user:secret@example.test/x",
        "https://example.test:22/x",
    ],
)
def test_private_credentialed_and_unsupported_destinations_are_blocked(url):
    with pytest.raises(egress.EgressBlocked):
        egress.assert_public_url(url)


def test_all_dns_answers_must_be_public(monkeypatch):
    _dns(monkeypatch, "203.0.113.8", "10.0.0.4")
    with pytest.raises(egress.EgressBlocked):
        egress.assert_public_url("https://mixed.example.test/path")


def test_domain_allowlist_is_suffix_safe(monkeypatch):
    _dns(monkeypatch, "8.8.8.8")
    monkeypatch.setenv("OCD_EGRESS_ALLOW_DOMAINS", "example.test")
    assert egress.assert_public_url("https://api.example.test/x")
    with pytest.raises(egress.EgressBlocked):
        egress.assert_public_url("https://example.test.attacker.invalid/x")


def test_public_destination_is_allowed(monkeypatch):
    _dns(monkeypatch, "8.8.8.8")
    assert egress.assert_public_url("https://example.test/path")


def test_remote_mcp_loopback_destination_is_blocked():
    with pytest.raises(egress.EgressBlocked):
        egress.assert_public_url("http://127.0.0.1:8000/mcp")
