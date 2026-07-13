# Open Claude Desktop — agent knowledge base

Model-agnostic (BYOK) Claude Desktop clone. All implementations are original —
no proprietary Anthropic code, assets, branding, or verbatim system prompts.

## Architecture

- `backend/` — FastAPI + SSE (port 8000). All product logic lives in
  `backend/ocd_core/` (agent loop `agent.run_turn`, providers, knowledge/RAG,
  MCP registry, code execution, Cowork, scheduler, settings, keychain secrets).
  Routes in `backend/app/routes/` are thin wrappers.
- Providers (`ocd_core/llm/`): one OpenAI-compatible client drives every backend
  EXCEPT `anthropic`, which uses `llm/anthropic_native.py` — a native Messages-API
  adapter behind the same `chat.completions.create` shape, for prompt caching +
  extended thinking. Request shape is model-family-aware (always-on/adaptive/budget
  thinking, sampling-param rejection); thinking blocks that precede tool calls are
  cached by tool-call id and replayed. Tests: `test_anthropic_native.py`.
- `desktop/` — the flagship client: React 18 + TS + Vite (dev port 1420 → :8000)
  inside a Tauri v2 shell (`desktop/src-tauri/`). PyInstaller freezes the backend
  as the `ocd-backend` sidecar; a pinned Node runtime ships as `ocd-node` for
  `.mcpb` extensions (backend sees it as `OCD_NODE`).
- `frontend/` — the LEGACY Reflex web client (`aj360_app`), still tested in CI.
  Backend-level fixes serve both clients; prefer fixing in `ocd_core`.
- Secrets: OS keychain via `ocd_core.secrets` (service "open-claude-desktop"),
  never plaintext files. Tests force a MemoryStore (autouse conftest fixture).

## Desktop security / durability posture (2026-07 hardening)

The packaged app is a local-first BYOK desktop, but its backend is a real HTTP
server on loopback. Five contracts keep that safe and durable — do not regress
them (tests: `test_hardening_blockers.py`, `test_bash_jail.py`, `test_cowork.py`):

- **Stable data root** — `config._default_data_root()`: `AJ360_DATA_DIR` (the shell
  sets it to a per-user dir) → a frozen build's per-OS user-data dir → dev repo root.
  A frozen build must NEVER derive its root from `__file__` (that's the ephemeral
  PyInstaller `_MEIPASS`, wiped every restart).
- **Loopback API token** — the shell mints a per-launch token, passes it to the
  sidecar as `OCD_API_TOKEN`, and injects it into the webview as
  `window.__OCD_API_TOKEN__` (client sends it as `X-OCD-Token`). `app.main`'s
  middleware rejects any request lacking it *when the env is set* (health probes
  exempt). Unset (dev/web) → no enforcement. This closes drive-by RCE: a web page
  can reach the port but can't read the token.
- **Host allowlist** — `TrustedHostMiddleware` (env `OCD_ALLOWED_HOSTS`, defaults to
  loopback names + `testserver`) defeats DNS rebinding.
- **Unattended tool posture** — `agent.background_tool_flags(gated)`. Cowork/scheduler
  runs are `permission_mode="auto"` with the HITL gate OFF, so they get `gated=False`
  → NO code_execution/bash/text_editor (else injected content = unsupervised RCE).
  Only `approval="manual"` (live gate) passes `gated=True` for the full toolset.
- **Bash allowlist** — `integrations._BASH_ALLOW` is read-only/non-spawning only;
  `find` is excluded (its `-exec/-delete` run arbitrary programs).
- **Autonomy guardrails** — the EFFORT step cap bounds one turn's main loop; two more
  bound the amplifiers it doesn't (tests: `test_autonomy_guardrails.py`, `test_scheduler.py`):
  `config.MAX_SUBAGENTS_PER_TURN` caps subagent fan-out (each is a full nested turn);
  `config.TURN_TOKEN_BUDGET` is a runaway cost ceiling — once a turn's reported tokens
  cross it the loop lands on the finalize synthesis (best-effort, so a no-op for
  providers that don't report usage); `config.SCHEDULER_SKIP_OVERLAP` stops a scheduled
  automation from stacking a second copy while its prior run is still active.
- **Crash/migration durability** (tests: `test_durability.py`): a running Cowork task
  flushes its transcript incrementally (`cowork._FLUSH_INTERVAL_SEC` throttle), not only
  at the end, so a crash mid-run keeps the work so far. A SQLite schema change snapshots
  the DB first via `engine.backup_sqlite_before_migration()` (`VACUUM INTO` → a
  consistent copy incl. WAL) — and only when a migration actually runs.

## How uploaded files reach the model (post-incident contract)

There are TWO attachment paths — don't conflate them:

1. **Composer attachments** (paperclip/drag in the chat box): the desktop client
   reads text files client-side and inlines them into the goal as
   `Attached file: name\n\n```…```` blocks (`desktop/src/state/attachments.ts`);
   images ride as data-URI vision parts. Fully visible to the model, no RAG.
2. **Project knowledge uploads** (Project → files): saved to
   `projects/<pid>/knowledge/<name>`, chunked + embedded into per-project
   ChromaDB. Reaches the model three ways, ALL of which must stay intact:
   - `search_project_knowledge` tool — ungated, added whenever a project is
     active (`agent.run_turn`).
   - `agent._knowledge_files_section` — the system prompt lists the project's
     uploaded filenames and explicitly forbids hunting the disk / guessing paths.
   - Code-execution mirror — `integrations._exec_workdir` stat-syncs the raw
     files into `<workspace>/knowledge/` so `run code` can transform the actual
     bytes ("modify this CSV"); originals stay pristine, mirror files never show
     up as produced files (synced before the snapshot).

**Incident (2026-07):** a user uploaded a CSV and asked for modifications; the
model — blind to the upload and armed with filesystem MCP tools — hallucinated a
"Claude CoWork" folder, searched the disk, and asked the user where the file was.
An external fix branch (`fix/attached-file-visibility-in-agent-turn`, never
pushed) diagnosed this against a months-old tree (Reflex-only, `frontend/ocd_app`,
BigQuery-gated retrieval); its retrieval-gating fix was already superseded by the
P0-1 ungated tool. The still-valid parts (prompt file listing, no-path-guessing
guidance) were ported to the current architecture and extended with the exec
workspace mirror. Tests: `backend/tests/test_knowledge_visibility.py`.

## Working conventions

- Verify before pushing: backend `pytest` + `ruff check .` (CI uses latest ruff),
  desktop `npm run typecheck && npm run test && npm run build`, and `cargo check
  --locked` in `desktop/src-tauri` when the shell changed (CI now runs this too —
  the `shell` job).
- `desktop/src-tauri/binaries/` needs both sidecars staged for `cargo check`
  (stub ok for `ocd-backend`; `desktop/scripts/fetch-node-sidecar.sh` for node).
  The CI `shell` job stubs BOTH sidecars + a placeholder `desktop/dist` so
  tauri-build's externalBin / frontendDist existence checks pass.
- Never commit `backend/settings.json` changes (`git checkout` it before staging).
- Delivery: PR per feature batch; 6 CI checks (backend/frontend/desktop/shell/lint/
  secrets); the user merges. After merge, reset the working branch onto main.
