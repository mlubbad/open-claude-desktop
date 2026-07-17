import io
import tempfile

import pytest
from fastapi import HTTPException, UploadFile


def _capture_tempfiles(monkeypatch, tmp_path, route):
    created = []
    real_named_tempfile = tempfile.NamedTemporaryFile

    def create(**kwargs):
        tmp = real_named_tempfile(dir=tmp_path, **kwargs)
        created.append(tmp.name)
        return tmp

    monkeypatch.setattr(route.tempfile, "NamedTemporaryFile", create)
    return created


def test_bundle_spool_rejects_upload_over_shared_cap(monkeypatch, tmp_path):
    from app.routes import integrations as route
    from ocd_core import knowledge

    monkeypatch.setattr(knowledge, "MAX_UPLOAD_BYTES", 8)
    created = _capture_tempfiles(monkeypatch, tmp_path, route)
    upload = UploadFile(filename="large.mcpb", file=io.BytesIO(b"123456789"))

    with pytest.raises(HTTPException) as exc:
        route._spool_upload(upload)
    assert exc.value.status_code == 413
    assert created
    assert all(not tmp_path.joinpath(tempfile_name).exists()
               for tempfile_name in created)


def test_bundle_spool_accepts_upload_at_cap(monkeypatch, tmp_path):
    from app.routes import integrations as route
    from ocd_core import knowledge

    monkeypatch.setattr(knowledge, "MAX_UPLOAD_BYTES", 8)
    _capture_tempfiles(monkeypatch, tmp_path, route)
    upload = UploadFile(filename="small.mcpb", file=io.BytesIO(b"12345678"))

    path = route._spool_upload(upload)
    try:
        assert path.read_bytes() == b"12345678"
    finally:
        path.unlink(missing_ok=True)
