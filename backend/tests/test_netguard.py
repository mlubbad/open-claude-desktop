"""Tests for ocd_core.netguard -- the fail-closed auth/binding guard.

Pure, stdlib-only helpers used by app.py to refuse serving an unauthenticated
app on a non-loopback interface (e.g. the Docker default `--host 0.0.0.0`).
"""
import pytest
from ocd_core import netguard as n


# --- is_loopback_host ------------------------------------------------------- #
def test_loopback_hosts():
    for h in ("127.0.0.1", "127.0.0.5", "::1", "localhost", "LOCALHOST", " 127.0.0.1 "):
        assert n.is_loopback_host(h) is True, h


def test_non_loopback_hosts():
    for h in ("0.0.0.0", "::", "192.168.1.10", "10.0.0.1", "example.com", "", "   "):
        assert n.is_loopback_host(h) is False, h


# --- effective_bind_host ---------------------------------------------------- #
def test_effective_bind_host_from_cli_flag():
    assert n.effective_bind_host(
        argv=["chainlit", "run", "app.py", "--host", "0.0.0.0"], env={}) == "0.0.0.0"
    assert n.effective_bind_host(argv=["x", "--host=0.0.0.0"], env={}) == "0.0.0.0"


def test_effective_bind_host_from_env():
    assert n.effective_bind_host(
        argv=["chainlit", "run", "app.py"], env={"CHAINLIT_HOST": "0.0.0.0"}) == "0.0.0.0"


def test_effective_bind_host_defaults_to_loopback():
    # No --host flag and no env override => Chainlit's DEFAULT_HOST (loopback).
    assert n.effective_bind_host(argv=["chainlit", "run", "app.py"], env={}) == "127.0.0.1"


def test_cli_flag_wins_over_env():
    assert n.effective_bind_host(
        argv=["x", "--host", "127.0.0.1"], env={"CHAINLIT_HOST": "0.0.0.0"}) == "127.0.0.1"


# --- require_authenticated_binding ------------------------------------------ #
def test_guard_allows_when_auth_configured():
    # Public bind is fine as long as auth is on.
    n.require_authenticated_binding(
        auth_configured=True, host="0.0.0.0", allow_unauthenticated=False)


def test_guard_allows_loopback_without_auth():
    # No auth is acceptable on loopback (frictionless local dev).
    n.require_authenticated_binding(
        auth_configured=False, host="127.0.0.1", allow_unauthenticated=False)


def test_guard_allows_explicit_optout_on_public_bind():
    # Operators fronting the app with their own auth can opt out explicitly.
    n.require_authenticated_binding(
        auth_configured=False, host="0.0.0.0", allow_unauthenticated=True)


def test_guard_raises_on_public_bind_without_auth():
    with pytest.raises(RuntimeError):
        n.require_authenticated_binding(
            auth_configured=False, host="0.0.0.0", allow_unauthenticated=False)


# --- allow_unauthenticated (shared opt-out flag) ---------------------------- #
def test_allow_unauthenticated_reads_env(monkeypatch):
    monkeypatch.delenv("OCD_ALLOW_UNAUTHENTICATED", raising=False)
    assert n.allow_unauthenticated() is False
    for v in ("1", "true", "TRUE", "yes", "Yes"):
        monkeypatch.setenv("OCD_ALLOW_UNAUTHENTICATED", v)
        assert n.allow_unauthenticated() is True, v
    for v in ("0", "false", "no", ""):
        monkeypatch.setenv("OCD_ALLOW_UNAUTHENTICATED", v)
        assert n.allow_unauthenticated() is False, v
