# Contributing

## Prerequisites

- **Python 3.12** (the canonical interpreter; `venv312/` on the maintainer's box).
- Node.js + npm (for the Reflex frontend build).
- Docker (optional — for Postgres chat history and for the sandboxed
  `code_execution` tool).

## Setup

```bash
python -m venv venv312
venv312/Scripts/activate            # Windows  (use source venv312/bin/activate on POSIX)
pip install -e ".[chainlit,reflex,dev]"
cp .env.example .env                # then fill in ZHIPU_API_KEY, auth, GCP, etc.
pre-commit install                  # ruff + gitleaks gates
```

Authenticate BigQuery with Application Default Credentials
(`gcloud auth application-default login`) — do **not** add a service-account key
file to the repo.

## Running the apps

```bash
# Chainlit chat app  (:8000)
chainlit run app.py                 # run.py wraps this on Python 3.14+

# Reflex projects UI (:3000)  — run from the app dir; npm backend on Windows
cd aj360_app && REFLEX_USE_NPM=true reflex run

# Postgres for chat history (optional)
docker compose up -d
```

`.claude/launch.json` also defines both servers for the editor's preview tooling.

## Tests, lint, types

```bash
pytest                  # or: python tests/test_sql_guard.py  (each test file is self-running)
ruff check .            # lint
ruff format .           # format
mypy app.py aj360_app   # types
```

## Conventions

- **Branch before changing `main`**; open a PR rather than pushing to `main`.
- Keep secrets out of the tree (`.env`, key files are git-ignored; `gitleaks`
  blocks commits).
- BigQuery access is read-only by default; gate any write behind
  `AJ360_ALLOW_WRITES` and a human approval.
- Don't put docs under `knowledge/` — it is ingested into the agent's RAG
  (`rglob("*.md")`). Use `docs/`.
