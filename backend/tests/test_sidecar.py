"""The frozen-backend entry point stays importable and wired to the FastAPI app.

Guards the PyInstaller sidecar recipe (the frozen binary is built + smoke-tested in
the release pipeline; here we just keep the entry point from silently breaking).
"""
import sys
from pathlib import Path

# sidecar.py is a top-level script under backend/, not an installed package module.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def test_sidecar_module_exposes_main():
    import sidecar

    assert callable(sidecar.main)


def test_backend_app_serves_health_for_freezing():
    from app.main import app
    from fastapi.testclient import TestClient

    resp = TestClient(app).get("/healthz")
    assert resp.status_code == 200
    assert resp.json().get("status") == "ok"
