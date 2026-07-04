# Open Claude Desktop

An open-source, **model-agnostic** desktop assistant in the spirit of Claude Desktop —
Chat, Projects, Knowledge, MCP connectors, Plugins, Skills, and an agentic tool-using
reasoning loop. The one deliberate difference from Claude Desktop: **you bring your own
models and keys** — open/hosted models of your choice, not a single vendor.

> **Status.** The codebase is transitioning from its origin as a BigQuery analytics
> agent ("AJ360") into the general-purpose, model-agnostic clone described in
> [`docs/superpowers/specs/2026-07-02-claude-desktop-clone-architecture.md`](docs/superpowers/specs/2026-07-02-claude-desktop-clone-architecture.md).
> See the [full repository review](docs/reviews/2026-07-02-full-repository-review.md)
> for the origin story and the 8-phase roadmap. **Done:** BYOK model-agnostic core
> (any OpenAI-compatible provider — OpenAI, Groq, OpenRouter, DeepSeek, Zhipu/GLM,
> Together, Mistral, local Ollama/vLLM/LM Studio, …; keys in the OS keychain); a general
> assistant with BigQuery as an **optional connector**; the **React/TypeScript + Tauri
> desktop client** (`desktop/`) with Chat, Projects, Artifacts, MCP connectors, Plugins +
> marketplace, Skills, a Code tab and a Cowork tab (subagents, plan mode, scheduled
> automations); and the **`ocd` CLI**. The legacy Reflex client (`frontend/`) is retired.

## Architecture

Two services in one repo, communicating over HTTP + SSE. The backend owns all domain
logic and data; the frontend is a thin client.

| Path | Role |
|------|------|
| `backend/ocd_core/` | Framework-agnostic domain layer: agent loop + typed streaming events, LLM client, MCP client, tools, projects/conversations/knowledge, auth, secrets, persistence |
| `backend/app/` | FastAPI HTTP + SSE surface over `ocd_core` |
| `backend/ocd_cli/` | The `ocd` terminal client over `ocd_core` (interactive + headless) |
| `desktop/` | The React/TypeScript + Vite + Tauri desktop client (the active UI) |
| `mcp_servers/` | Bundled demo MCP server |
| `plugins/`, `skills/`, `content/marketplace/` | Drop-in agent tools, skills, and the bundled plugin catalog |

The invariant: `ocd_core` never imports FastAPI or any UI/transport — the CLI, the
desktop app, and a self-hosted server are all thin frontends over one engine.

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

The fastest way to try it is the terminal client:

```bash
ocd -p "Explain what a model-agnostic BYOK assistant is, in two sentences."
# or just `ocd` for an interactive session
```

For the full desktop UI, run the backend and the React/Tauri client (`desktop/`) in
two terminals:

```bash
# 1) Backend on http://127.0.0.1:8000 (binds loopback; runs open/anonymous locally)
cd backend && uvicorn app.main:app --reload

# 2) The desktop client (dev server on http://localhost:1420, proxies /api → :8000)
cd desktop && npm install && npm run dev
```

With `DATABASE_URL=sqlite:///./ocd.db` (the default in `.env.example`) the schema is
created automatically on first start — no database to set up. For a packaged native
window instead of the browser, use `cd desktop && npm run tauri dev` (needs Rust + the
platform WebView libs). Postgres is optional: `docker compose up -d` brings one up and
the backend uses it when `DATABASE_URL` is unset.

BigQuery (optional) authenticates via Application Default Credentials
(`gcloud auth application-default login`) or Workload Identity — never a committed key.

## Tests

```bash
pytest backend/tests                              # backend (run from the repo root)
cd desktop && npm run typecheck && npm run test   # desktop client
```

## Contributing & security

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`SECURITY.md`](SECURITY.md). Licensed under
the [MIT License](LICENSE).
