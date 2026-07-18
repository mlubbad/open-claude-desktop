"""OCD_* env vars supersede the legacy AJ360_* names, and the AJ360_* names keep
working (back-compat) so existing configs/tests aren't broken by the rename.
"""
import importlib

import pytest


@pytest.fixture
def reload_config(monkeypatch):
    for v in ("OCD_DATA_DIR", "AJ360_DATA_DIR", "OCD_ALLOW_WRITES", "AJ360_ALLOW_WRITES"):
        monkeypatch.delenv(v, raising=False)

    def _reload():
        import ocd_core.config as c
        return importlib.reload(c)
    return _reload


def test_data_dir_prefers_ocd_then_falls_back(reload_config, monkeypatch, tmp_path):
    aj, ocd = tmp_path / "aj", tmp_path / "ocd"
    monkeypatch.setenv("AJ360_DATA_DIR", str(aj))
    assert str(reload_config().REPO_ROOT) == str(aj)          # legacy still works
    monkeypatch.setenv("OCD_DATA_DIR", str(ocd))
    assert str(reload_config().REPO_ROOT) == str(ocd)         # new name wins


def test_allow_writes_prefers_ocd_then_falls_back(reload_config, monkeypatch):
    monkeypatch.setenv("AJ360_ALLOW_WRITES", "true")
    assert reload_config().ALLOW_WRITES is True               # legacy still works
    monkeypatch.setenv("OCD_ALLOW_WRITES", "false")
    assert reload_config().ALLOW_WRITES is False              # new name wins


def test_auth_secret_accepts_ocd_and_legacy(monkeypatch):
    import ocd_core.auth as auth
    for v in ("APP_AUTH_SECRET", "CHAINLIT_AUTH_SECRET", "OCD_AUTH_SECRET", "AJ360_AUTH_SECRET"):
        monkeypatch.delenv(v, raising=False)
    monkeypatch.setenv("OCD_AUTH_SECRET", "s3cret")
    assert auth._secret() == b"s3cret"
    monkeypatch.delenv("OCD_AUTH_SECRET")
    monkeypatch.setenv("AJ360_AUTH_SECRET", "legacy")
    assert auth._secret() == b"legacy"
