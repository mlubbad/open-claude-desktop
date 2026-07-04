"""Phase 0 (H2): connector fetches are SSRF-guarded and don't leak auth on redirect."""
import pytest
from ocd_core import integrations as I


def test_blocked_host_rejects_private_and_loopback():
    assert I._blocked_host("127.0.0.1") is True
    assert I._blocked_host("10.0.0.1") is True
    assert I._blocked_host("169.254.169.254") is True   # cloud metadata endpoint
    assert I._blocked_host("") is True


def test_safe_outbound_get_blocks_private_target():
    with pytest.raises(I.ConnectorBlocked):
        I._safe_outbound_get("http://127.0.0.1:8000/", {"User-Agent": "x"})
    with pytest.raises(I.ConnectorBlocked):
        I._safe_outbound_get("http://169.254.169.254/latest/meta-data/", {})


def test_safe_outbound_get_rejects_non_http_scheme():
    with pytest.raises(I.ConnectorBlocked):
        I._safe_outbound_get("file:///etc/passwd", {})
    with pytest.raises(I.ConnectorBlocked):
        I._safe_outbound_get("ftp://example.com/x", {})


def test_test_connector_reports_blocked(monkeypatch):
    monkeypatch.setattr(I, "_load_user_connectors",
                        lambda: [{"id": "c1", "name": "c", "base_url": "http://10.1.2.3",
                                  "header_key": "", "header_value": ""}])
    out = I.test_connector("c1")
    assert "Blocked" in out


def test_call_connector_reports_blocked(monkeypatch):
    monkeypatch.setattr(I, "_load_user_connectors",
                        lambda: [{"id": "c1", "name": "c", "base_url": "http://127.0.0.1",
                                  "header_key": "Authorization", "header_value": "secret"}])
    out = I.call_connector("c1", "/data")
    assert "blocked" in out.lower()
