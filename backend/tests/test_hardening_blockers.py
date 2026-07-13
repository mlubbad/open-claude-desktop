"""Production-hardening blockers (audit Week-1/Week-2).

Covers the backend-observable half of the hardening PR:

* B1  — stable per-user data root for a FROZEN build (packaged app must not write
        into its ephemeral PyInstaller extraction dir and lose everything on restart).
* B6  — settings.json / schedules.json now persist through the ATOMIC jsonstore
        helper (a crash mid-write can never truncate them to junk that reads back
        as "reset to defaults" / "no automations").
* B4  — an UNATTENDED background run withholds the destructive local tools.
* B3a — Host allowlist (TrustedHost) rejects a foreign Host header (DNS-rebinding).
* B3b — the per-launch loopback API token gates every request when set, but never
        the health probes.

The Tauri-shell half (token mint + webview injection + kill-on-exit) is verified by
`cargo check`; CI does not compile Rust.
"""
from __future__ import annotations

import importlib
import sys

import pytest
from fastapi.testclient import TestClient

# --- B1: frozen-build data root -------------------------------------------------

def _reload_config():
    return importlib.reload(importlib.import_module("ocd_core.config"))


def test_data_root_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("AJ360_DATA_DIR", str(tmp_path / "custom"))
    cfg = _reload_config()
    assert cfg.REPO_ROOT == tmp_path / "custom"
    assert cfg.REPO_ROOT.is_dir()  # created on import


def test_frozen_build_uses_per_user_dir_not_meipass(monkeypatch, tmp_path):
    # Simulate a PyInstaller onefile build with no explicit data dir. The root must
    # land under the per-OS user-data location, NOT next to the (ephemeral) binary.
    monkeypatch.delenv("AJ360_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    cfg = _reload_config()
    try:
        assert cfg.REPO_ROOT == tmp_path / "xdg" / "OpenClaudeDesktop"
        assert cfg.REPO_ROOT.is_dir()
    finally:
        monkeypatch.setattr(sys, "frozen", False, raising=False)
        _reload_config()  # restore module for the rest of the suite


def test_dev_source_root_is_repo(monkeypatch):
    monkeypatch.delenv("AJ360_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    cfg = _reload_config()
    # Two levels up from ocd_core/config.py is the repo root (which holds backend/).
    assert (cfg.REPO_ROOT / "backend" / "ocd_core").is_dir()


# --- B6: atomic settings / schedules persistence --------------------------------

def test_settings_save_is_atomic_and_roundtrips(monkeypatch, tmp_path):
    from ocd_core import config, settings
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    settings.save_settings({"model": "fast-mistral", "effort": "Max"})
    # No temp file left behind (atomic replace cleaned up).
    assert not (tmp_path / "settings.json.tmp").exists()
    assert settings.get_settings()["model"] == "fast-mistral"
    assert settings.get_settings()["effort"] == "Max"


def test_schedules_save_is_atomic(monkeypatch, tmp_path):
    from ocd_core import scheduler
    store = scheduler.ScheduleStore(tmp_path / "schedules.json")
    s = scheduler.Schedule(id="abc123", goal="ping", kind="interval", every_seconds=60)
    store.save([s])
    assert not (tmp_path / "schedules.json.tmp").exists()
    loaded = store.load()
    assert len(loaded) == 1 and loaded[0].id == "abc123" and loaded[0].goal == "ping"


# --- B4: unattended background runs drop the destructive tools ------------------

def test_background_tool_flags_ungated_withholds_local_tools():
    from ocd_core import agent
    flags = agent.background_tool_flags(gated=False)
    # Destructive local tools OFF for an unattended (gate-off) run.
    assert flags["code_exec"] is False
    assert flags["bash"] is False
    assert flags["text_editor"] is False
    # Read/browse/orchestrate stay ON so automations still function.
    assert flags["web_search"] and flags["web_fetch"] and flags["subagents"]


def test_background_tool_flags_gated_restores_full_toolset():
    from ocd_core import agent
    flags = agent.background_tool_flags(gated=True)
    assert flags["code_exec"] and flags["bash"] and flags["text_editor"]


# --- B3a / B3b: Host allowlist + loopback API token -----------------------------

@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_foreign_host_header_rejected(client):
    # TrustedHost defaults to the loopback names + testserver; a foreign Host is a
    # DNS-rebinding attempt and must 400 before reaching any route.
    r = client.get("/healthz", headers={"host": "evil.example.com"})
    assert r.status_code == 400


def test_token_required_when_set(client, monkeypatch):
    monkeypatch.setattr("app.main._API_TOKEN", "s3cr3t-token")
    # No token → 401.
    assert client.get("/settings").status_code == 401
    # Correct token → passes the gate (auth disabled → 200).
    monkeypatch.delenv("APP_USERNAME", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    ok = client.get("/settings", headers={"X-OCD-Token": "s3cr3t-token"})
    assert ok.status_code == 200
    # Wrong token → 401 (constant-time compare, but still rejects).
    assert client.get("/settings", headers={"X-OCD-Token": "nope"}).status_code == 401


def test_health_probes_bypass_token(client, monkeypatch):
    monkeypatch.setattr("app.main._API_TOKEN", "s3cr3t-token")
    assert client.get("/healthz").status_code == 200


def test_no_token_env_means_no_enforcement(client, monkeypatch):
    # Dev / plain-web default: token unset → behavior unchanged, no 401.
    monkeypatch.setattr("app.main._API_TOKEN", "")
    monkeypatch.delenv("APP_USERNAME", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    assert client.get("/settings").status_code == 200
