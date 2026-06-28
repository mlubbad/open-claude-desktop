"""Smoke + pure-logic tests for ocd_core.schema_catalog.

No BigQuery / ChromaDB is touched. We verify the module imports cleanly, that
the public surface (ensure_catalog / search_schema / _build_catalog_sync) is
present, and that _catalog_version_matches reads the on-disk version file under
a tmp AJ360_DATA_DIR exactly like the original core.py.
"""
import importlib

import pytest


@pytest.fixture
def sc(monkeypatch, tmp_path):
    monkeypatch.setenv("AJ360_DATA_DIR", str(tmp_path))
    import ocd_core.config as c
    importlib.reload(c)
    import ocd_core.schema_catalog as s
    importlib.reload(s)
    return s, c


def test_public_surface_importable(sc):
    s, _ = sc
    for name in ("ensure_catalog", "search_schema", "_build_catalog_sync",
                 "_catalog_version_matches", "_schema_catalog", "_kb_documents"):
        assert hasattr(s, name), f"schema_catalog missing {name}"
    assert callable(s.ensure_catalog)
    assert callable(s.search_schema)
    assert callable(s._build_catalog_sync)


def test_catalog_version_matches_false_when_absent(sc):
    s, _ = sc
    assert s._catalog_version_matches() is False


def test_catalog_version_matches_roundtrip(sc):
    s, c = sc
    vf = c._CATALOG_VERSION_FILE
    vf.parent.mkdir(parents=True, exist_ok=True)
    vf.write_text(c._CATALOG_VERSION)
    assert s._catalog_version_matches() is True
    vf.write_text("not-the-version")
    assert s._catalog_version_matches() is False
