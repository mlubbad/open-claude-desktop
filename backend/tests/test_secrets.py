"""Phase 0 (C3): secrets live in a keychain/encrypted store, never plaintext on disk."""
import json

import pytest
from ocd_core import secrets


@pytest.fixture(autouse=True)
def _reset():
    secrets.reset_store()
    yield
    secrets.reset_store()


def test_memory_backend_roundtrip(monkeypatch):
    monkeypatch.setenv("OCD_SECRET_BACKEND", "memory")
    s = secrets.get_secret_store()
    assert isinstance(s, secrets.MemoryStore)
    s.set("k", "v")
    assert s.get("k") == "v"
    s.delete("k")
    assert s.get("k") is None


def test_encrypted_file_backend_roundtrip(tmp_path):
    store = secrets.EncryptedFileStore(path=tmp_path / "secrets.enc")
    store.set("provider:openai", "sk-123")
    # A second instance (same key file) must decrypt what the first wrote.
    store2 = secrets.EncryptedFileStore(path=tmp_path / "secrets.enc")
    assert store2.get("provider:openai") == "sk-123"
    # The on-disk blob must NOT contain the plaintext secret.
    raw = (tmp_path / "secrets.enc").read_bytes()
    assert b"sk-123" not in raw
    store.delete("provider:openai")
    assert secrets.EncryptedFileStore(path=tmp_path / "secrets.enc").get("provider:openai") is None


def test_backend_override(monkeypatch, tmp_path):
    monkeypatch.setenv("OCD_SECRET_BACKEND", "file")
    monkeypatch.setattr(secrets.config, "REPO_ROOT", tmp_path)
    assert isinstance(secrets.get_secret_store(), secrets.EncryptedFileStore)


def test_connector_secret_is_externalized(monkeypatch, tmp_path):
    from ocd_core import integrations as I

    monkeypatch.setenv("OCD_SECRET_BACKEND", "memory")
    secrets.reset_store()
    monkeypatch.setattr(I, "CONNECTORS_FILE", tmp_path / "connectors.json")

    item = I.add_connector("My API", "https://api.example.com",
                           header_key="Authorization", header_value="Bearer TOPSECRET")
    assert item["has_secret"] is True
    assert "header_value" not in item  # plaintext not returned in the record

    # The persisted file must not contain the secret anywhere.
    disk = (tmp_path / "connectors.json").read_text()
    assert "TOPSECRET" not in disk
    assert '"has_secret": true' in disk.lower()

    # But it resolves through the store for real requests.
    saved = I._load_user_connectors()[0]
    assert I._connector_header_value(saved) == "Bearer TOPSECRET"

    # Removal also clears the secret.
    I.remove_connector(item["id"])
    assert secrets.get_secret_store().get(I._connector_secret_key(item["id"])) is None
    assert json.loads((tmp_path / "connectors.json").read_text()) == []


def test_legacy_inline_header_value_still_resolves():
    from ocd_core import integrations as I
    legacy = {"id": "c1", "header_key": "X-Key", "header_value": "legacy-plain"}
    assert I._connector_header_value(legacy) == "legacy-plain"
