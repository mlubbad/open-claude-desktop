"""Phase 0 (C1): the network-exposure guard fails CLOSED.

A non-loopback bind with auth disabled — the historical default — is an
unauthenticated-RCE surface (POST /mcp-servers executes an arbitrary command).
These tests pin the fail-closed contract.
"""
import importlib

import pytest


def _fresh():
    import ocd_core.auth
    importlib.reload(ocd_core.auth)
    import ocd_core.netguard as ng
    return importlib.reload(ng)


def _disable_auth(monkeypatch):
    for k in ("APP_USERNAME", "APP_PASSWORD", "APP_AUTH_SECRET",
              "CHAINLIT_AUTH_SECRET", "OCD_AUTH_SECRET"):
        monkeypatch.delenv(k, raising=False)


def _enable_auth(monkeypatch):
    monkeypatch.setenv("APP_USERNAME", "u")
    monkeypatch.setenv("APP_PASSWORD", "p")
    monkeypatch.setenv("APP_AUTH_SECRET", "s")


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "", "127.5.5.5"])
def test_loopback_hosts_are_loopback(monkeypatch, host):
    ng = _fresh()
    assert ng.is_loopback(host) is True


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "10.0.0.5", "192.168.1.9",
                                  "example.com", "8.8.8.8"])
def test_public_hosts_are_not_loopback(monkeypatch, host):
    ng = _fresh()
    assert ng.is_loopback(host) is False


def test_default_bind_is_loopback(monkeypatch):
    monkeypatch.delenv("OCD_BIND_HOST", raising=False)
    ng = _fresh()
    assert ng.bind_host() == "127.0.0.1"
    assert ng.binding_is_safe() is True
    ng.assert_safe_binding()  # must not raise


def test_public_bind_without_auth_fails_closed(monkeypatch):
    _disable_auth(monkeypatch)
    monkeypatch.delenv("OCD_ALLOW_INSECURE_NETWORK", raising=False)
    monkeypatch.setenv("OCD_BIND_HOST", "0.0.0.0")
    ng = _fresh()
    assert ng.binding_is_safe() is False
    assert ng.unsafe_binding_reason() is not None
    with pytest.raises(RuntimeError):
        ng.assert_safe_binding()


def test_public_bind_with_auth_is_allowed(monkeypatch):
    _enable_auth(monkeypatch)
    monkeypatch.setenv("OCD_BIND_HOST", "0.0.0.0")
    ng = _fresh()
    assert ng.binding_is_safe() is True
    ng.assert_safe_binding()  # must not raise


def test_insecure_optin_cannot_bypass_authentication(monkeypatch):
    _disable_auth(monkeypatch)
    monkeypatch.setenv("OCD_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("OCD_ALLOW_INSECURE_NETWORK", "1")
    ng = _fresh()
    assert ng.binding_is_safe() is False
    with pytest.raises(RuntimeError, match="authentication"):
        ng.assert_safe_binding()


def test_multi_tenant_loopback_requires_authentication(monkeypatch):
    _disable_auth(monkeypatch)
    monkeypatch.setenv("OCD_BIND_HOST", "127.0.0.1")
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    ng = _fresh()
    assert ng.binding_is_safe() is False
    assert "multi-tenant" in (ng.unsafe_binding_reason() or "")


def test_multi_tenant_loopback_with_auth_is_allowed(monkeypatch):
    _enable_auth(monkeypatch)
    monkeypatch.setenv("OCD_BIND_HOST", "127.0.0.1")
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    ng = _fresh()
    assert ng.binding_is_safe() is True
    ng.assert_safe_binding()
