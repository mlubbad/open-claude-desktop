# Open Claude Desktop

An open-source, **model-agnostic** desktop assistant in the spirit of Claude Desktop —
Chat, Projects, Knowledge, MCP connectors, Plugins, Skills, and an agentic tool-using
reasoning loop. The one deliberate difference from Claude Desktop: **you bring your own
models and keys** — open/hosted models of your choice, not a single vendor.

> **Hosted/public launch is FROZEN.** Local loopback desktop development remains
> supported, but hosted, public-network, multi-tenant operation and public release
> publishing are blocked by a source-controlled policy. See
> [`docs/launch-freeze.md`](docs/launch-freeze.md).

> **Status.** The codebase is transitioning from its origin as a BigQuery analytics
> agent ("AJ360") into the general-purpose, model-agnostic clone described in
> [`docs/superpowers/specs/2026-07-02-claude-desktop-clone-architecture.md`](docs/superpowers/specs/2026-07-02-claude-desktop-clone-architecture.md).
> See the [full repository review](docs/reviews/2026-07-02-full-repository-review.md)
> for the origin story and the 8-phase roadmap. **Done:** BYOK model-agnostic core
> (any OpenAI-compatible provider — NVIDIA NIM (default, GLM-5.2), OpenAI, Anthropic,
> Google Gemini, Vertex AI (ADC), Groq,
> OpenRouter, DeepSeek, Zhipu/GLM,
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

## Harness (code workspaces)

Attach a chat to a local folder and the agent becomes a coding agent scoped to that
folder — a Claude-Code-style **harness** layered on the same engine (`backend/ocd_core/harness/`):

- **File tools** jailed to the workspace: `read_file`, `edit_file` (unique-`old_string`
  guard), `write_file` (read-before-overwrite), `glob`, `grep` — behind a
  symlink/junction-safe path jail. These are the coding workhorses.
- **Run in the folder** — in a workspace, `bash` runs build/test **runners** (`pytest`,
  `npm test`, `cargo test`, `python script.py`, …) in the attached folder via a curated
  allowlist. Interpreters run the repo's own script files but inline code (`-c`/`-e`/
  `--eval`/stdin) and interactive REPLs are blocked, path args can't leave the workspace,
  and secret-shaped env vars are stripped from the subprocess. Runners prompt by default
  (`allow` a command to auto-run it); `rm -rf /`-class stays hard-blocked in every mode.
- **Permission modes** — `default` (prompt), `acceptEdits` (auto-approve jailed edits +
  safe bash), `plan` (read-only), `strict`, `bypass` — plus `allow`/`deny`/`ask` rules
  (`bash(git *)`, `edit_file(src/**)`; precedence deny > ask > allow > mode). A
  workspace's `.claude/settings.json` permission rules are honored. Sensitive built-ins
  (`code_execution`, etc.) always keep their existing approval prompt; `rm -rf /`-class
  commands are hard-blocked in every mode. Secret-shaped paths (`.env`, `*.pem`, `id_*`)
  stay write-gated even in `acceptEdits`.
- **Checkpoints & rewind** — files are snapshotted before each edit; a per-message rewind
  restores them (checkpoints are bound to their workspace, so one folder can never
  restore into another).
- **Plan card & tool timeline** — a model-driven task plan and per-tool activity/diffs
  stream into the chat.
- **Hooks** — run your own shell command at lifecycle events (`SessionStart`,
  `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`). It receives the event as JSON
  on stdin and can inject context, block a prompt, or tighten a tool decision
  (`allow`/`deny`/`ask`) — Claude Code's hook contract, so existing hook scripts port over.
  Hooks are configured in **app settings only** (never loaded from a workspace folder,
  because a hook *executes* where a workspace permission rule only *restricts*), run with
  the same secret-stripped environment as workspace bash, and receive tool input as stdin
  JSON — never interpolated into their command line. A `PreToolUse` hook that fails, times
  out, or emits garbage **denies** the call rather than silently allowing it; the same
  goes for a hook that asks for approval in an unattended run where no one can answer.

Workspace + checkpoint APIs live under `/harness/workspaces`. Execution is on the host
behind the jail + permission gate (an opt-in container runner is a later phase). Design
and roadmap: `docs/superpowers/specs/2026-07-20-harness-design.md`; hooks:
`docs/superpowers/specs/2026-07-22-harness-hooks-design.md`.

## Security posture (local-first)

- **Fail-closed networking.** The backend binds `127.0.0.1` by default and *refuses to
  start* on a non-loopback interface during the hosted/public launch freeze. The
  explicit development-only Compose carve-out is documented in `launchguard.py`; the
  older insecure-network opt-in alone cannot bypass the freeze or authentication.
- **Containment defaults.** Authentication is mandatory for tenancy/non-loopback
  binding. Remote marketplaces, stdio MCP, host execution, and scheduled autonomous
  work default off; Cowork is manual and sensitive tools use `ask`. Database and
  migration failures abort startup instead of silently falling back or continuing.
- **Bounded ingress.** Direct launches enforce body/concurrency caps; Compose routes
  through a temporary Nginx policy with request, connection, rate, and upload limits.
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
platform WebView libs). Postgres is optional: before `docker compose up -d`, configure
`APP_USERNAME`, `APP_PASSWORD`, and `APP_AUTH_SECRET` in `.env`; Compose binds the
backend non-loopback on its private network and therefore fails closed without them.

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
