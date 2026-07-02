# Open Claude Desktop

An open-source, **model-agnostic** desktop assistant in the spirit of Claude Desktop —
Chat, Projects, Knowledge, MCP connectors, Plugins, Skills, and an agentic tool-using
reasoning loop. The one deliberate difference from Claude Desktop: **you bring your own
models and keys** — open/hosted models of your choice, not a single vendor.

> **Status.** The codebase is mid-transition from its origin as a BigQuery analytics
> agent ("AJ360") into the general-purpose, model-agnostic clone described in
> [`docs/superpowers/specs/2026-07-02-claude-desktop-clone-architecture.md`](docs/superpowers/specs/2026-07-02-claude-desktop-clone-architecture.md).
> See the [full repository review](docs/reviews/2026-07-02-full-repository-review.md)
> for the current state and the 8-phase roadmap. Today the model backend is Zhipu GLM;
> a provider abstraction (OpenAI-compatible, local Ollama/vLLM, etc.) lands in Phase 1,
> and BigQuery becomes an optional connector in Phase 2.

## Architecture

Two services in one repo, communicating over HTTP + SSE. The backend owns all domain
logic and data; the frontend is a thin client.

| Path | Role |
|------|------|
| `backend/ocd_core/` | Framework-agnostic domain layer: agent loop + typed streaming events, LLM client, MCP client, tools, projects/conversations/knowledge, auth, secrets, persistence |
| `backend/app/` | FastAPI HTTP + SSE surface over `ocd_core` |
| `frontend/aj360_app/` | Reflex (Python→React) thin client (being rebuilt as a React/TypeScript + Tauri desktop app in Phase 3) |
| `mcp_servers/` | Bundled demo MCP server |
| `plugins/`, `skills/` | Drop-in agent tools and skills |

The invariant: `ocd_core` never imports FastAPI, Reflex, or any UI/transport — the CLI,
the desktop app, and a self-hosted server are all thin frontends over one engine.

## Security posture (local-first)

- **Fail-closed networking.** The backend binds `127.0.0.1` by default and *refuses to
  start* on a non-loopback interface unless authentication is configured (or the
  explicit `OCD_ALLOW_INSECURE_NETWORK=1` dev opt-in is set). See `ocd_core/netguard.py`.
- **Secrets in the OS keychain.** Connector credentials (and, from Phase 1, provider API
  keys) are stored via `keyring` with an encrypted-file fallback — never plaintext in
  tracked files. See `ocd_core/secrets.py`.
- **Sandboxed tools.** `code_execution` runs only inside a container (`docker --network
  none`) or refuses; `bash` is allowlisted and path-jailed to a sandbox; `web_fetch` and
  REST connectors block private/internal hosts (SSRF) and don't leak auth on redirect.
- **Read-only BigQuery** (optional connector): non-`SELECT` is rejected; per-project
  table allowlist enforced on parsed `referenced_tables`; hard bytes-billed cost cap.

## Setup

```bash
python3.12 -m venv .venv && source .venv/bin/activate   # POSIX
pip install -e "./backend[dev]"
cp .env.example .env            # pick a provider (LLM_PROVIDER) + set its API key
```

## Run

```bash
# 1) Postgres + backend via Docker (recommended):
docker compose up -d --build           # backend on http://127.0.0.1:8000

# — or — run the backend directly:
cd backend && uvicorn app.main:app --reload   # binds 127.0.0.1 by default

# 2) The (transitional) Reflex frontend, in another terminal:
cd frontend && reflex run
```

BigQuery (optional) authenticates via Application Default Credentials
(`gcloud auth application-default login`) or Workload Identity — never a committed key.

## Tests

```bash
pytest backend/tests                 # backend (run from the repo root)
cd frontend && pytest                # frontend
```

## Contributing & security

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`SECURITY.md`](SECURITY.md). Licensed under
the [MIT License](LICENSE).
