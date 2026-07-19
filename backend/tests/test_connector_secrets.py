"""REST connector API tokens must not land in the git-tracked connectors.json.
They live in a gitignored sidecar (.connector_secrets.json) and are resolved at
call time by _connector_secret().
"""
import importlib
import json

import pytest


@pytest.fixture
def ig(monkeypatch, tmp_path):
    monkeypatch.setenv("AJ360_DATA_DIR", str(tmp_path))
    import ocd_core.config as c
    importlib.reload(c)
    import ocd_core.integrations as i
    importlib.reload(i)
    yield i
    # The reload above re-bound module-level paths (PLUGINS_DIR, CONNECTORS_FILE)
    # to tmp_path. Undo the env patch and reload again so later test FILES see
    # the real module state (else e.g. plugin dispatch resolves an empty tmp dir).
    monkeypatch.undo()
    importlib.reload(c)
    importlib.reload(i)


def test_add_connector_keeps_token_out_of_connectors_file(ig, tmp_path):
    ig.add_connector("GitHub", "https://api.github.com", "Authorization", "Bearer SECRET123")
    conn_raw = (tmp_path / "connectors.json").read_text(encoding="utf-8")
    assert "SECRET123" not in conn_raw
    assert "Bearer" not in conn_raw
    # ...but the header KEY (non-secret) is still recorded for the request.
    assert "Authorization" in conn_raw
    # the secret lives in the gitignored sidecar
    secrets = json.loads((tmp_path / ".connector_secrets.json").read_text(encoding="utf-8"))
    assert "Bearer SECRET123" in secrets.values()


def test_connector_secret_resolved_at_call_time(ig):
    item = ig.add_connector("API", "https://api.example.com", "X-Key", "tok-42")
    cid = item["id"]
    assert ig._connector_secret(cid) == "tok-42"
    # the persisted metadata carries no secret
    loaded = next(u for u in ig._load_user_connectors() if u["id"] == cid)
    assert "tok-42" not in json.dumps(loaded)


def test_call_connector_sends_the_secret_header(ig, monkeypatch):
    item = ig.add_connector("API", "https://api.example.com", "X-Key", "sekret")
    cid = item["id"]
    captured = {}

    class _R:
        status_code = 200
        text = "ok"
        url = "https://api.example.com/x"

    monkeypatch.setattr(ig, "_http_get",
                        lambda url, headers, timeout=15, **kw: captured.update(headers=headers) or _R())
    ig.call_connector(cid, "/x")
    assert captured["headers"].get("X-Key") == "sekret"


def test_remove_connector_drops_the_secret(ig, tmp_path):
    item = ig.add_connector("API", "https://api.example.com", "X-Key", "tok-99")
    cid = item["id"]
    ig.remove_connector(cid)
    assert ig._connector_secret(cid) == ""
    sidecar = tmp_path / ".connector_secrets.json"
    if sidecar.exists():
        assert cid not in json.loads(sidecar.read_text(encoding="utf-8"))
