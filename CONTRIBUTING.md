# Contributing

## Prerequisites

- **Python 3.12** (the canonical interpreter).
- Node.js + npm (for the transitional Reflex frontend build).
- Docker (optional — for Postgres and for the sandboxed `code_execution` tool).

## Setup

```bash
python3.12 -m venv .venv && source .venv/bin/activate   # (Windows: .venv\Scripts\activate)
pip install -e "./backend[dev]"
pip install --no-deps -r backend/constraints.txt        # hold zhipuai v2 (Phase 1 removes this)
cp .env.example .env                                    # fill in your model key, auth, etc.
pre-commit install                                      # ruff + gitleaks gates
```

BigQuery (optional connector) authenticates via Application Default Credentials
(`gcloud auth application-default login`) — do **not** add a service-account key
file to the repo.

## Running the apps

```bash
# Backend (FastAPI + SSE) — binds 127.0.0.1 by default
cd backend && uvicorn app.main:app --reload            # :8000

# Transitional Reflex frontend, in another terminal
cd frontend && reflex run                              # :3000

# Or the whole backend stack (Postgres + backend) via Docker
docker compose up -d --build
```

## Tests, lint, types

```bash
pytest backend/tests    # backend (from the repo root)
cd frontend && pytest   # frontend
ruff check .            # lint
ruff format .           # format
mypy backend/ocd_core backend/app   # types
```

## Conventions

- **Branch before changing `main`**; open a PR rather than pushing to `main`.
- Keep secrets out of the tree (`.env`, key files are git-ignored; `gitleaks`
  blocks commits).
- BigQuery access is read-only by default; gate any write behind
  `AJ360_ALLOW_WRITES` and a human approval.
- Don't put docs under `knowledge/` — it is ingested into the agent's RAG
  (`rglob("*.md")`). Use `docs/`.
