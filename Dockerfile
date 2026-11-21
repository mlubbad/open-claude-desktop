# FastAPI model-agnostic agent service (standalone / self-hosted container).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY backend/pyproject.toml backend/alembic.ini ./backend/
COPY backend/ocd_core ./backend/ocd_core
COPY backend/app ./backend/app
COPY backend/ocd_cli ./backend/ocd_cli
RUN pip install ./backend

# Runtime defaults and bundled marketplace catalog (mutable state lives under OCD_DATA_DIR).
COPY settings.json ./
COPY content ./content
COPY mcp_servers ./mcp_servers
COPY plugins ./plugins

EXPOSE 8000

ENV OCD_BIND_HOST=0.0.0.0
CMD ["sh", "-c", "set -e; cd backend; alembic upgrade head; exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
