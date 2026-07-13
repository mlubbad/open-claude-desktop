"""Phase 2c: upload byte cap + zip-bomb guards (production-readiness audit F-12)."""
import io
import zipfile

import pytest
from ocd_core import integrations as I
from ocd_core import knowledge as K


def test_read_upload_rejects_oversized_and_accepts_within_limit():
    assert K.read_upload(io.BytesIO(b"x" * 30), limit=50) == b"x" * 30
    with pytest.raises(K.UploadTooLarge):
        K.read_upload(io.BytesIO(b"x" * 100), limit=50)


def test_read_zip_member_caps_decompressed_bytes(monkeypatch, tmp_path):
    monkeypatch.setattr(K, "_MAX_ZIP_MEMBER_BYTES", 100)
    zp = tmp_path / "z.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("big.xml", b"a" * 5000)   # a small compressed member that expands past the cap
        z.writestr("ok.xml", b"hello")
    with zipfile.ZipFile(zp) as z:
        with pytest.raises(K.ExtractionError):
            K._read_zip_member(z, "big.xml")
        assert K._read_zip_member(z, "ok.xml") == b"hello"


def test_mcpb_extract_rejects_a_size_bomb(monkeypatch, tmp_path):
    monkeypatch.setattr(I, "_MCPB_MAX_TOTAL_BYTES", 100)
    zp = tmp_path / "b.mcpb"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("big.bin", b"a" * 5000)   # expands to 5000 > the 100-byte cap
    dest = tmp_path / "out"
    dest.mkdir()
    with zipfile.ZipFile(zp) as z:
        with pytest.raises(I.McpbError):
            I._mcpb_safe_extract(z, dest)


def test_mcpb_extract_rejects_too_many_entries(monkeypatch, tmp_path):
    monkeypatch.setattr(I, "_MCPB_MAX_ENTRIES", 3)
    zp = tmp_path / "b.mcpb"
    with zipfile.ZipFile(zp, "w") as z:
        for i in range(10):
            z.writestr(f"f{i}.txt", b"x")
    dest = tmp_path / "out"
    dest.mkdir()
    with zipfile.ZipFile(zp) as z:
        with pytest.raises(I.McpbError):
            I._mcpb_safe_extract(z, dest)


def test_upload_route_413s_an_oversized_file(db, monkeypatch):
    from app.main import app
    from fastapi.testclient import TestClient
    from ocd_core import projects
    monkeypatch.setattr(K, "MAX_UPLOAD_BYTES", 10)
    p = projects.create_project("P")
    c = TestClient(app)
    r = c.post(f"/projects/{p['id']}/files",
               files={"file": ("big.txt", b"x" * 100, "text/plain")})
    assert r.status_code == 413
