"""Days 1-3 containment: hosted/public launch stays frozen until P0 gates pass.

These tests are intentionally policy tests, not only implementation tests.  A future
change may lift the freeze, but it must change the runtime, release, and documented
contracts together in a reviewed commit.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _guard():
    from ocd_core import launchguard

    return launchguard


def _clear_deployment_env(monkeypatch):
    for key in (
        "OCD_DEPLOYMENT_MODE",
        "OCD_BIND_HOST",
        "OCD_ALLOW_INSECURE_NETWORK",
        "OCD_MULTI_TENANT",
    ):
        monkeypatch.delenv(key, raising=False)


def test_local_loopback_remains_available(monkeypatch):
    _clear_deployment_env(monkeypatch)
    guard = _guard()

    assert guard.deployment_mode() == "local"
    assert guard.launch_block_reason() is None
    guard.assert_launch_allowed()


@pytest.mark.parametrize("mode", ["hosted", "public"])
def test_declared_hosted_or_public_mode_is_frozen_even_on_loopback(monkeypatch, mode):
    _clear_deployment_env(monkeypatch)
    monkeypatch.setenv("OCD_DEPLOYMENT_MODE", mode)
    guard = _guard()

    reason = guard.launch_block_reason("127.0.0.1")
    assert reason and "frozen" in reason.lower()
    with pytest.raises(RuntimeError, match="frozen"):
        guard.assert_launch_allowed("127.0.0.1")


def test_multi_tenant_mode_is_frozen_even_when_bound_to_loopback(monkeypatch):
    _clear_deployment_env(monkeypatch)
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    guard = _guard()

    reason = guard.launch_block_reason("127.0.0.1")
    assert reason and "multi-tenant" in reason.lower()


def test_non_loopback_local_mode_cannot_bypass_freeze_with_old_escape_hatch(monkeypatch):
    _clear_deployment_env(monkeypatch)
    monkeypatch.setenv("OCD_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("OCD_ALLOW_INSECURE_NETWORK", "1")
    guard = _guard()

    reason = guard.launch_block_reason()
    assert reason and "non-loopback" in reason.lower()


def test_authentication_does_not_turn_the_freeze_into_a_hosted_launch_bypass(monkeypatch):
    _clear_deployment_env(monkeypatch)
    monkeypatch.setenv("OCD_BIND_HOST", "0.0.0.0")
    monkeypatch.setenv("APP_USERNAME", "operator")
    monkeypatch.setenv("APP_PASSWORD", "secret")
    monkeypatch.setenv("APP_AUTH_SECRET", "signing-key")
    guard = _guard()

    reason = guard.launch_block_reason()
    assert reason and "non-loopback" in reason.lower()


@pytest.mark.parametrize("opt_in,blocked", [(None, True), ("1", False)])
def test_non_loopback_development_requires_explicit_insecure_opt_in(
    monkeypatch, opt_in, blocked
):
    _clear_deployment_env(monkeypatch)
    monkeypatch.setenv("OCD_DEPLOYMENT_MODE", "development")
    monkeypatch.setenv("OCD_BIND_HOST", "0.0.0.0")
    if opt_in:
        monkeypatch.setenv("OCD_ALLOW_INSECURE_NETWORK", opt_in)
    guard = _guard()

    assert (guard.launch_block_reason() is not None) is blocked


def test_unknown_deployment_mode_fails_closed(monkeypatch):
    _clear_deployment_env(monkeypatch)
    monkeypatch.setenv("OCD_DEPLOYMENT_MODE", "prod-ish")
    guard = _guard()

    reason = guard.launch_block_reason("127.0.0.1")
    assert reason and "unknown" in reason.lower()


def test_desktop_release_check_passes_while_hosted_stays_frozen(monkeypatch, capsys):
    guard = _guard()

    assert guard.HOSTED_PUBLIC_LAUNCH_FROZEN is True
    assert guard.DESKTOP_RELEASE_FROZEN is False
    assert guard.main(["--check-public-release"]) == 0

    monkeypatch.setattr(guard, "DESKTOP_RELEASE_FROZEN", True)
    assert guard.main(["--check-public-release"]) == 1
    assert "blocked" in capsys.readouterr().err.lower()


def test_application_startup_enforces_launch_guard(monkeypatch):
    from app import main

    def blocked():
        raise RuntimeError("hosted/public launch is frozen")

    monkeypatch.setattr(main.launchguard, "assert_launch_allowed", blocked)
    with pytest.raises(RuntimeError, match="launch is frozen"):
        with _start(main.app):
            pass


def _start(app):
    """Import TestClient lazily so the production module never needs to export it."""
    from fastapi.testclient import TestClient

    return TestClient(app)


def test_release_workflow_and_policy_document_are_frozen():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    policy_path = ROOT / "docs" / "launch-freeze.md"

    assert "launch-policy:" in workflow
    assert "needs: launch-policy" in workflow
    assert "python -m ocd_core.launchguard --check-public-release" in workflow
    assert policy_path.is_file()
    policy = policy_path.read_text(encoding="utf-8")
    assert "HOSTED_PUBLIC_LAUNCH_FROZEN" in policy
    assert "HOSTED_PUBLIC_LAUNCH_FROZEN" in policy


def test_compose_is_explicitly_development_not_hosted():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert 'OCD_DEPLOYMENT_MODE: "development"' in compose
