"""Workspace tenancy — the out-of-SQL stores (SaaS slice 2).

Extends the project/conversation scoping of test_tenancy.py to the three stores that
live outside the row model: keychain secrets, the settings file, and vector collections.
Same two axes: flag OFF is a byte-for-byte no-op; flag ON isolates non-local workspaces
while the implicit `local` workspace keeps inheriting the pre-tenancy data.
"""
import pytest
from ocd_core import chroma, config, tenancy
from ocd_core import secrets as sec
from ocd_core import settings as st

# ---- secrets -------------------------------------------------------------------------

def test_secrets_flag_off_is_unprefixed(monkeypatch):
    """No enforcement → get_secret_store() is the raw backend (the backend-selection
    contract and existing single-user keys are untouched)."""
    monkeypatch.setenv("OCD_SECRET_BACKEND", "memory")
    sec.reset_store()
    store = sec.get_secret_store()
    assert isinstance(store, sec.MemoryStore)  # not wrapped when off
    store.set("provider:openai", "sk-legacy")
    assert store.get("provider:openai") == "sk-legacy"


def test_secrets_isolated_between_workspaces(monkeypatch):
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    with tenancy.use_workspace("wsA"):
        sec.get_secret_store().set("provider:openai", "sk-A")
    with tenancy.use_workspace("wsB"):
        assert sec.get_secret_store().get("provider:openai") is None
        sec.get_secret_store().set("provider:openai", "sk-B")
    with tenancy.use_workspace("wsA"):
        assert sec.get_secret_store().get("provider:openai") == "sk-A"  # untouched by B
    with tenancy.use_workspace("wsB"):
        sec.get_secret_store().delete("provider:openai")
        assert sec.get_secret_store().get("provider:openai") is None
    with tenancy.use_workspace("wsA"):
        assert sec.get_secret_store().get("provider:openai") == "sk-A"  # B's delete is local to B


def test_secrets_local_inherits_legacy_keys(monkeypatch):
    # Written with tenancy OFF → an unprefixed (legacy) key on the backend.
    sec.get_secret_store().set("k", "legacy")
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    with tenancy.use_workspace(tenancy.LOCAL_WORKSPACE):
        assert sec.get_secret_store().get("k") == "legacy"  # local owns pre-tenancy secrets
    with tenancy.use_workspace("newcomer"):
        assert sec.get_secret_store().get("k") is None      # a new tenant does not


# ---- settings ------------------------------------------------------------------------

@pytest.fixture
def settings_file(monkeypatch, tmp_path):
    monkeypatch.setattr(st.config, "SETTINGS_FILE", tmp_path / "settings.json")
    return tmp_path


def test_settings_flag_off_uses_base_file(settings_file):
    st.save_settings({"model": "m-legacy"})
    assert (settings_file / "settings.json").exists()
    assert st.get_settings()["model"] == "m-legacy"


def test_settings_isolated_between_workspaces(settings_file, monkeypatch):
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    with tenancy.use_workspace("wsA"):
        st.save_settings({"model": "model-A"})
    with tenancy.use_workspace("wsB"):
        assert st.get_settings()["model"] == config.DEFAULT_SETTINGS["model"]  # not A
        st.save_settings({"model": "model-B"})
    with tenancy.use_workspace("wsA"):
        assert st.get_settings()["model"] == "model-A"
    # Physically separate sibling files; the base file is never written by a non-local tenant.
    assert (settings_file / "settings.wsA.json").exists()
    assert (settings_file / "settings.wsB.json").exists()
    assert not (settings_file / "settings.json").exists()


def test_settings_local_inherits_base_file(settings_file, monkeypatch):
    st.save_settings({"model": "m-legacy"})  # flag off → base file
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    with tenancy.use_workspace(tenancy.LOCAL_WORKSPACE):
        assert st.get_settings()["model"] == "m-legacy"        # local reads the base file
    with tenancy.use_workspace("newcomer"):
        assert st.get_settings()["model"] == config.DEFAULT_SETTINGS["model"]


# ---- vector collections (naming only — no ChromaDB client needed) --------------------

def test_chroma_flag_off_and_local_keep_historical_name(monkeypatch):
    assert chroma.project_kb_collection_name("proj") == "kb_project_proj"
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    with tenancy.use_workspace(tenancy.LOCAL_WORKSPACE):
        assert chroma.project_kb_collection_name("proj") == "kb_project_proj"


def test_chroma_names_isolated_stable_and_bounded(monkeypatch):
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    with tenancy.use_workspace("wsA"):
        a = chroma.project_kb_collection_name("proj")
        assert chroma.project_kb_collection_name("proj") == a          # deterministic
    with tenancy.use_workspace("wsB"):
        b = chroma.project_kb_collection_name("proj")
    assert a != b and a != "kb_project_proj" and b != "kb_project_proj"  # isolated
    # ChromaDB's collection-name rules: <=63 chars, alnum/underscore/hyphen.
    assert len(a) <= 63 and all(ch.isalnum() or ch in "_-" for ch in a)


def test_chroma_name_bounded_for_long_project_ids(monkeypatch):
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    with tenancy.use_workspace("wsA"):
        name = chroma.project_kb_collection_name("x" * 80)
    assert len(name) <= 63
