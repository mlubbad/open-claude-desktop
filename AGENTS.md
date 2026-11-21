# Architecture & Contributor Agent Guide

Open-source, model-agnostic (BYOK) desktop workspace for chat, live artifacts, MCP tools,
and jailed local coding workflows. All implementations and bundled assets are 100% open-source
(MIT code + SIL Open Font License 1.1 typography).

## Architecture

- `backend/` - FastAPI + SSE engine (`backend/ocd_core/`), thin HTTP routes (`backend/app/`),
  and terminal client (`backend/ocd_cli/`, installed as `ocd`).
- `desktop/` - Native desktop application: React 18 + TypeScript + Vite inside a Tauri v2
  Rust shell (`desktop/src-tauri/`). PyInstaller freezes the backend into `ocd-backend`
  (bound to `127.0.0.1:18410` with a per-launch `X-OCD-Token`), alongside `ocd-node` for
  zero-dependency `.mcpb` extensions.
- Secrets: Stored in the OS keychain via `ocd_core.secrets` (with encrypted Fernet fallback
  on headless Linux), never plaintext tracked files.

## Attachment & Knowledge Contract

1. **Composer attachments** (paperclip / drag-and-drop / paste): text files inline into the
   turn goal (`desktop/src/state/attachments.ts`); images ride as vision data-URIs.
2. **Project knowledge uploads**: chunked into per-project ChromaDB and exposed via
   `search_project_knowledge`, listed in `agent._knowledge_files_section`, and stat-synced
   read-only into `<workspace>/knowledge/` for code execution.

## Pre-PR Verification Checklist

- Backend: `pytest backend/tests` and `ruff check .`
- Wheel check: `pip wheel ./backend --no-deps -w /tmp/whl` (ensure new subpackages are in `pyproject.toml`)
- Desktop: `cd desktop && npm run typecheck && npm run test && npm run build`
- Rust shell (when `desktop/src-tauri` changes): `cargo check --locked`
- Never commit personal `settings.json` overrides or `.env` files.
