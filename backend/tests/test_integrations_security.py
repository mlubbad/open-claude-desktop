"""Security guards in ocd_core.integrations.

#4  run_bash must not let an allowlisted reader escape the sandbox via an
    absolute path (cat /etc/passwd, dir C:\\Users, find /, cat ~/.ssh/...).
#5  _http_get (user REST connectors) must block private/internal hosts before
    the request and after redirects -- parity with web_fetch.
"""
import subprocess

import httpx
import pytest

from ocd_core import integrations


# --- #4  run_bash absolute-path jail ---------------------------------------- #
def test_run_bash_blocks_absolute_posix_path():
    out = integrations.run_bash("cat /etc/passwd")
    assert out.startswith("Rejected")
    assert "absolute" in out.lower()


def test_run_bash_blocks_windows_drive_path():
    # Assert on the distinctive "absolute" marker, not just "Rejected": on Windows
    # cat/dir aren't real exes, so a missing-binary "Rejected" would pass spuriously.
    assert "absolute" in integrations.run_bash("dir C:\\Users").lower()
    assert "absolute" in integrations.run_bash("cat C:/Windows/win.ini").lower()


def test_run_bash_blocks_home_and_root_scan():
    assert "absolute" in integrations.run_bash("cat ~/.ssh/id_rsa").lower()
    assert "absolute" in integrations.run_bash("find / -name id_rsa").lower()


def test_run_bash_allows_relative_command(monkeypatch):
    # A relative, allowlisted command must NOT trip the abs-path guard. Stub
    # subprocess.run so the result doesn't depend on the OS having the binary.
    class _P:
        stdout = "hello\n"
        stderr = ""
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _P())
    assert "hello" in integrations.run_bash("echo hello")


# --- #5  _http_get SSRF guard ----------------------------------------------- #
def test_http_get_blocks_loopback(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not issue a request to a blocked host")))
    with pytest.raises(ValueError):
        integrations._http_get("http://127.0.0.1:8000/admin", {})


def test_http_get_blocks_link_local_metadata(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("must not issue a request to a blocked host")))
    with pytest.raises(ValueError):
        integrations._http_get("http://169.254.169.254/latest/meta-data/", {})


def test_http_get_blocks_non_http_scheme():
    with pytest.raises(ValueError):
        integrations._http_get("file:///etc/passwd", {})


def test_http_get_allows_public_host(monkeypatch):
    monkeypatch.setattr(integrations, "_blocked_host", lambda h: False)

    class _R:
        url = "https://api.example.com/v1"
        status_code = 200
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _R())
    r = integrations._http_get("https://api.example.com/v1", {})
    assert r.status_code == 200


def test_http_get_blocks_redirect_to_private(monkeypatch):
    monkeypatch.setattr(integrations, "_blocked_host", lambda h: h == "169.254.169.254")

    class _R:
        url = "http://169.254.169.254/latest/meta-data"
        status_code = 200
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _R())
    with pytest.raises(ValueError):
        integrations._http_get("http://api.example.com/x", {})
