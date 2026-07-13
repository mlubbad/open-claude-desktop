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


# ---- Phase 2b: web_fetch redirect revalidation + byte cap; origin-based auth strip ----

class _Resp:
    def __init__(self, status, headers, chunks=b""):
        self.status_code = status
        self.headers = headers
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_bytes(self):
        for i in range(0, len(self._chunks), 50):
            yield self._chunks[i:i + 50]


def test_web_fetch_revalidates_a_redirect_to_a_blocked_host(monkeypatch):
    import httpx
    # Only the metadata IP is "blocked"; the public first hop resolves fine (offline,
    # _blocked_host would otherwise fail closed on every name).
    monkeypatch.setattr(I, "_blocked_host", lambda h: "169.254" in h)

    class C:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, _method, url, headers=None):
            # A public first hop that 302-redirects to the cloud metadata endpoint.
            if "meta" not in url:
                return _Resp(302, {"location": "http://169.254.169.254/latest/"})
            return _Resp(200, {"content-type": "text/html"}, b"<html>secret</html>")

    monkeypatch.setattr(httpx, "Client", C)
    I._FETCH_CACHE.clear()
    out, _ = I.web_fetch("http://example.com/start")
    assert "url_not_allowed" in out  # the redirect hop was re-checked and blocked


def test_web_fetch_caps_the_body(monkeypatch):
    import httpx
    monkeypatch.setattr(I, "_blocked_host", lambda h: False)
    monkeypatch.setattr(I, "_WEB_FETCH_MAX_BYTES", 100)
    big = b"<html>" + b"a" * 5000 + b"</html>"

    class C:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, _method, _url, headers=None):
            return _Resp(200, {"content-type": "text/html"}, big)

    monkeypatch.setattr(httpx, "Client", C)
    I._FETCH_CACHE.clear()
    out, _ = I.web_fetch("http://example.com/big")
    assert out.startswith("Fetched")
    assert len(out) < 400  # capped near 100 bytes, not the full 5k body


def test_safe_outbound_get_strips_auth_on_scheme_downgrade(monkeypatch):
    import httpx
    monkeypatch.setattr(I, "_blocked_host", lambda h: False)
    seen = []

    class R:
        def __init__(self, status, headers):
            self.status_code = status
            self.headers = headers

    class C:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, headers=None):
            seen.append((url, dict(headers)))
            if url.startswith("https://"):
                return R(302, {"location": "http://api.example.com/x"})  # same host, downgraded
            return R(200, {})

    monkeypatch.setattr(httpx, "Client", C)
    I._safe_outbound_get("https://api.example.com/", {"Authorization": "secret", "User-Agent": "x"},
                         auth_header="Authorization")
    assert len(seen) == 2
    assert "Authorization" in seen[0][1]        # sent to the original https origin
    assert "Authorization" not in seen[1][1]    # dropped on the http downgrade (cross-origin)
