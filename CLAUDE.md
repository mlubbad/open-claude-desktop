# Open Claude Desktop — agent knowledge base

Model-agnostic (BYOK) Claude Desktop clone. All implementations are original —
no proprietary Anthropic code, assets, branding, or verbatim system prompts.

## Architecture

- `backend/` — FastAPI + SSE (port 8000). All product logic lives in
  `backend/ocd_core/` (agent loop `agent.run_turn`, providers, knowledge/RAG,
  MCP registry, code execution, Cowork, scheduler, settings, keychain secrets).
  Routes in `backend/app/routes/` are thin wrappers.
- `desktop/` — the flagship client: React 18 + TS + Vite (dev port 1420 → :8000)
  inside a Tauri v2 shell (`desktop/src-tauri/`). PyInstaller freezes the backend
  as the `ocd-backend` sidecar; a pinned Node runtime ships as `ocd-node` for
  `.mcpb` extensions (backend sees it as `OCD_NODE`).
- `frontend/` — the LEGACY Reflex web client (`aj360_app`), still tested in CI.
  Backend-level fixes serve both clients; prefer fixing in `ocd_core`.
- Secrets: OS keychain via `ocd_core.secrets` (service "open-claude-desktop"),
  never plaintext files. Tests force a MemoryStore (autouse conftest fixture).

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
  desktop `npm run typecheck && npm run test && npm run build`, and `cargo check`
  in `desktop/src-tauri` when the shell changed (CI does NOT compile Rust).
- `desktop/src-tauri/binaries/` needs both sidecars staged for `cargo check`
  (stub ok for `ocd-backend`; `desktop/scripts/fetch-node-sidecar.sh` for node).
- Never commit `backend/settings.json` changes (`git checkout` it before staging).
- Delivery: PR per feature batch; 5 CI checks (backend/frontend/desktop/lint/
  secrets); the user merges. After merge, reset the working branch onto main.
