# Open Claude Desktop — FastAPI backend image (the model-agnostic agent service).
#
# This replaces the retired Chainlit image. The backend is the local-first
# sidecar the desktop shell drives; it can also run standalone for a self-hosted
# server deployment (configure auth in that case — see ocd_core/netguard.py).
#
# The React/TypeScript + Tauri client (Phase 3) ships separately; the current
# Reflex frontend is run locally during the transition (see README).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

# Install the backend package. Copy only what the install needs first so the
# dependency layer caches across source-only changes.
COPY backend/pyproject.toml backend/constraints.txt backend/alembic.ini ./backend/
COPY backend/ocd_core ./backend/ocd_core
COPY backend/app ./backend/app
RUN pip install ./backend \
    # Hold the working zhipuai v2 + compatible PyJWT (see backend/constraints.txt).
    && pip install --no-deps -r ./backend/constraints.txt

# Runtime configs the backend reads from the repo root (connectors / MCP / skills /
# plugins). Data dirs are created at runtime under AJ360_DATA_DIR.
COPY mcp_servers.json settings.json ./
COPY mcp_servers ./mcp_servers
COPY plugins ./plugins
COPY skills ./skills

EXPOSE 8000

# The container binds all interfaces; port mapping should restrict host exposure
# to loopback (see docker-compose.yml). OCD_ALLOW_INSECURE_NETWORK is required
# because binding 0.0.0.0 with auth disabled otherwise fails closed (netguard).
ENV OCD_BIND_HOST=0.0.0.0
# alembic resolves script_location relative to CWD, so upgrade from backend/;
# uvicorn imports the installed `app` package so its CWD is irrelevant.
CMD ["sh", "-c", "(cd backend && alembic upgrade head) || true; uvicorn app.main:app --host 0.0.0.0 --port 8000"]
