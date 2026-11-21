"""Frozen backend entry point — the PyInstaller sidecar for the desktop app.

Runs the FastAPI backend under uvicorn so the Tauri shell can bundle it as an
``externalBin`` sidecar; the desktop app then ships self-contained, with no system
Python required. Binds loopback by default (netguard refuses an unauthenticated
non-loopback bind), and honors ``OCD_BIND_HOST`` / ``OCD_PORT``.

Run directly for development:  ``python backend/sidecar.py --port 8000``
Freeze it:                      ``desktop/scripts/build-backend-sidecar.sh``
"""
from __future__ import annotations

import argparse
import os


def main() -> None:
    from ocd_core import netguard

    parser = argparse.ArgumentParser(description="VersoWork backend sidecar")
    parser.add_argument("--host", default=netguard.bind_host(),
                        help="bind host (default: OCD_BIND_HOST or 127.0.0.1)")
    parser.add_argument("--port", type=int, default=int(os.getenv("OCD_PORT", "8000")),
                        help="bind port (default: OCD_PORT or 8000)")
    args = parser.parse_args()

    import uvicorn
    from app.main import app

    # A single machine-readable ready line the shell can wait on before loading the UI.
    print(f"OCD_BACKEND_READY host={args.host} port={args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
