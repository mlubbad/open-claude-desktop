# Design: Open Claude Desktop — Model-Agnostic Clone Architecture & Roadmap

> **Date:** 2026-07-02 · **Status:** Approved to start (owner decisions locked below)
> **Companion:** [`docs/reviews/2026-07-02-full-repository-review.md`](../../reviews/2026-07-02-full-repository-review.md)
> **Supersedes / completes:** the deferred Phases 5–6 of
> `docs/superpowers/specs/2026-06-27-two-service-refactor-design.md`, and reframes the
> product from "BigQuery analytics agent" to "model-agnostic Claude Desktop clone."

## 1. Mission & the one deliberate difference

Build an open-source desktop application that reaches **functional and UX parity with
Anthropic's Claude Desktop** — Chat, Projects, Memory, Artifacts, Code (CLI + Code tab),
Cowork, MCP connectors, Plugins, Skills, and the agentic reasoning/output quality — with
exactly **one** intentional difference: it is **model-agnostic**. Users bring their own
API keys and choose any model — hosted (OpenAI-compatible, OpenRouter, Zhipu/GLM,
DeepSeek, Qwen, Mistral, Gemini, Anthropic) or local (Ollama, LM Studio, vLLM,
llama.cpp) — and everything is powered by that choice.

**IP boundary.** Parity means *behavior and UX*, not *code or assets*. We do not copy
Anthropic's proprietary source, branding, icons, or verbatim system prompts. The current
claude.ai-derived theme, the hard-coded plan badge, and any Anthropic-mirrored tool
output strings are re-originated. Open specifications that Anthropic itself publishes —
**MCP**, **Agent Skills**, **MCPB/.mcpb** — are adopted on their merits.

**Third-party services** are restricted to **free / open-source** options. Non-OSS
free-tier services (e.g. Brave/Tavily search) may appear only as optional, BYO-key
adapters behind an OSS-default interface.

## 2. Owner decisions (locked 2026-07-02)

| # | Decision | Choice | Consequence |
|---|---|---|---|
| D1 | Frontend + desktop shell | **React/TS + Tauri v2**, Python backend as sidecar | Highest parity ceiling; Reflex retired after parity reached |
| D2 | BigQuery/AJ360 domain | **Demote to an optional built-in connector** | General assistant is the product; analytics still available when enabled |
| D3 | Form factor | **Local-first desktop, single user**, OS keychain | Simplest secure default; multi-user server mode is later + additive |
| D4 | Execution now | Commit docs, then **start Phase 0** | Phase 0 depends on none of D1–D3 and is strictly good |

## 3. Target architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│  Tauri v2 desktop shell  (Rust)                                          │
│   tray · global-shortcut quick-chat · updater · deep-link · notify ·     │
│   single-instance · OS keychain · native file pickers                    │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │  React 18 + TS + Vite  (webview)                                   │   │
│  │   assistant-ui chat · artifacts side-panel (sandboxed iframe) ·    │   │
│  │   command palette · settings · Projects/Code/Cowork surfaces       │   │
│  └───────────────▲──────────────────────────────────────────────────┘   │
│                  │  HTTP + SSE  (localhost)   ◄── the service boundary    │
│  ┌───────────────┴──────────────────────────────────────────────────┐   │
│  │  FastAPI backend  (PyInstaller-frozen sidecar)                    │   │
│  │  app/ (routes, deps, sse, schemas)                                │   │
│  │  ┌────────────────────────────────────────────────────────────┐  │   │
│  │  │  ocd_core  — framework-agnostic domain (single source)      │  │   │
│  │  │   agent runtime (run_turn + typed events, subagents,        │  │   │
│  │  │     context mgmt, HITL permissions, verification)           │  │   │
│  │  │   llm/   ── ChatClient PORT + provider ADAPTERS  ◄── D-agnostic│ │   │
│  │  │   tools/ ── tool REGISTRY (built-ins + MCP + skills + conns) │  │   │
│  │  │   mcp/   ── stdio + streamable-HTTP + SSE clients + OAuth    │  │   │
│  │  │   artifacts/ · skills/ · plugins/ · connectors/ (incl. bigquery)│ │
│  │  │   knowledge/ · memory/ · conversations/ · projects/         │  │   │
│  │  │   sandbox/ (bwrap/Podman/Seatbelt) · web/ (search+fetch)     │  │   │
│  │  │   db/ (SQLModel + Alembic) · auth · secrets (keyring)        │  │   │
│  │  └────────────────────────────────────────────────────────────┘  │   │
│  └───────────────────────────────────────────────────────────────────┘  │
│  Local data (platformdirs):  SQLite (default) · Chroma · working folders │
└──────────────────────────────────────────────────────────────────────────┘
              ▲                                   ▲
      ocd CLI (Textual/Rich TUI + headless -p)    Optional: self-hosted server mode
      shares the SAME ocd_core engine             (fastapi-users, per-user data)
```

**The invariant** (carried forward from the prior refactor and reaffirmed): `ocd_core`
never imports FastAPI, Reflex, React, or any UI/transport. Domain logic lives in
`ocd_core`; transport in `app/`; presentation in the React client and the CLI. The CLI,
the desktop app, and any server deployment are three thin frontends over one engine.

## 4. Design patterns (named, with where they apply)

- **Ports & Adapters (Hexagonal)** — the backbone. Define ports in `ocd_core` and swap
  adapters:
  - `ChatClient` port → `OpenAICompatAdapter` (Zhipu/DeepSeek/Qwen/OpenRouter/Ollama/
    vLLM/LM Studio via `base_url`), `AnthropicAdapter`. **This is the mission's core.**
  - `SearchProvider` port → `SearxngProvider` (default), `DdgsProvider` (fallback),
    `BraveProvider`/`TavilyProvider` (optional BYO-key).
  - `Sandbox` port → `BubblewrapSandbox` (Linux), `SeatbeltSandbox` (macOS),
    `PodmanSandbox` (cross-platform), `DockerSandbox` (fallback).
  - `SecretStore` port → `KeyringStore` (default), `FernetFileStore` (headless fallback).
  - `Tool` port → all callable tools (built-ins, MCP tools, skills-as-tools, connectors).
- **Strategy** — model/effort selection: per-conversation model + per-task roles (a cheap
  model for titles/sub-queries, the chosen model for the turn), with capability-aware
  routing and fallback.
- **Registry** — a single `ToolRegistry` assembles the per-turn tool set from enabled
  built-ins + MCP servers + skills + connectors, and **enforces enablement at dispatch**
  (closing H6). Parallel registries for skills, plugins (as MCP servers), and slash
  commands.
- **Typed event protocol as a discriminated union** (Pydantic v2) — the existing SSE
  vocabulary extended with `artifact_open|delta|close|update`, `todo_update`,
  `approval_required`, `subagent_open|close`, `usage`, `skill_loaded`, `hook_ran`. One
  frozen wire contract shared by SSE, the CLI's JSONL headless mode, and tests.
- **Event-sourced-leaning transcript** — the conversation remains the source of truth
  (today a JSONB transcript); artifacts and their versions get their own tables; memory
  is derived from transcripts. Enables branching, rewind/checkpoints, and search.
- **Command pattern** — slash commands and hooks are commands with a uniform
  parse→resolve→execute contract, defined in `ocd_core` (never a UI shell), reused by CLI
  + desktop + server.
- **Progressive disclosure** — Agent Skills load metadata always, bodies on demand; large
  tool sets expose a `tool_search` meta-tool instead of flooding the context.
- **First-run wizard / builder** — provider key + model + working folder + profile, gated
  by first-run detection; writes secrets to the keychain.

## 5. Roadmap — 8 phases, each ships a working app + green tests

The prior refactor's discipline is retained: TDD-sliced, no big-bang, every phase leaves
the app runnable and the suite green. Phases 1–2 and 4–7 depend on Phase 0; the frontend
(Phase 3) can proceed in parallel with backend Phases 4–7 once the extended event
contract from Phase 2 is frozen.

### Phase 0 — Stop the bleeding (security + ops truth) · **starts now**
*No architecture change; depends on nothing above. Every item is strictly good.*
1. Close the **fail-open-auth RCE** (C1): default-deny; a locally-generated bearer token
   for the local app; the MCP-exec path never runs unauthenticated.
2. Fix the **`bash` absolute-path escape** (C2): resolve+jail every path arg to the
   session root now; the full OS sandbox lands in Phase 6.
3. Move **connector secrets to `keyring`** (C3) with a Fernet-file fallback; stop writing
   secrets to tracked JSON.
4. **Retire the legacy Chainlit surface** (C4): delete `app.py`, `.chainlit/`,
   `chainlit.md`, `schema.sql`, `run.py`; drop the `chainlit` extra; salvage any unported
   logic (dataset-scope SQL enforcement H4, stream salvage, HITL cost approval) into
   `ocd_core` first.
5. Repoint **Docker/compose/CI at the two-service app** (C4/C5): per-service CI matrix
   that installs each package and runs its real suite; a Linux-clean dependency set (no
   `pywin32` in the base); healthchecks.
6. Add a **LICENSE** (owner picks; MIT or Apache-2.0 recommended for an OSS clone) and
   scrub real third-party identifiers from `.env.example` (C7).
7. Apply the **SSRF guard to connectors** + strip auth on cross-origin redirect (H2);
   **rate-limit `/auth/login`** (H1); enforce **tool enablement at dispatch** (H6);
   tighten CORS (H7).

*Verify:* two services build and boot in compose; real suites run and pass in CI; a
default-config network deployment is no longer an open RCE.

### Phase 1 — The model-agnostic core (the differentiator)
- `ocd_core/llm/` with the `ChatClient` port + `OpenAICompatAdapter` and (optional
  extra) `AnthropicAdapter`; normalize streaming deltas, tool-call assembly,
  `reasoning_content`/thinking, and `usage` across providers.
- **BYOK**: key CRUD in the keychain; a model **catalog + capability detection**
  (context window, max output, vision, tools, reasoning, caching) from models.dev /
  LiteLLM metadata; **per-conversation model** override + per-task roles.
- Token counting (`tiktoken`), tolerant tool-arg parsing (`json-repair`), retry/backoff
  (`tenacity`), structured-output/JSON mode, prompt caching where supported.
- Replace the `zhipuai`-pinned test with **provider-shape contract tests** (`respx` +
  a stub OpenAI-compatible app).

*Verify:* the same conversation runs against Zhipu, an OpenAI-compatible endpoint, and a
local Ollama model; usage/cost surfaces; contract tests green.

### Phase 2 — De-specialize the agent (general assistant; BigQuery → connector)
- **Composable system prompt** (Jinja2 sections: persona/tone/tools/memory/skills/
  user-profile), original text; user profile + preferences slot (kills hard-coded
  identity, M3).
- **Tool registry**: tools become pluggable; **BigQuery** `search_schema`/`run_sql`
  (+ schema catalog, SQL guard, dataset-scope enforcement) move into
  `ocd_core/connectors/bigquery/` as an **optional, toggle-able** connector — no longer
  always-on in every turn (D2).
- Finish the **Phase-6 layout**: `backend/content/{skills,plugins}`, `runtime/` data dir
  via config, convert any remaining path-based tests to real imports.
- Freeze the **extended event contract** (artifacts/todos/approvals/usage/subagents) so
  the frontend can build against it.

*Verify:* a fresh install with no BigQuery config is a fully working general assistant;
enabling the BigQuery connector restores analytics; suites green.

### Phase 3 — React/TS + Tauri desktop client
- `desktop/` React 18 + TS + Vite app: `assistant-ui` chat reproducing the `state.py`
  reducer spec (thinking coalescing, tool cards, sources); `fetch-event-source`
  cancellable SSE; markdown/KaTeX/Shiki; TanStack Virtual transcript; Radix + Tailwind
  with an **original** palette; `cmdk` palette; `tinykeys` shortcuts; `i18next` + RTL.
- **Tauri v2 shell**: tray, global-shortcut quick-chat, updater, deep-link,
  notifications, single-instance, OS keychain; the FastAPI backend frozen (PyInstaller)
  as a **sidecar**; SQLite default via `platformdirs`.
- **Stop/cancel** generation (turn registry keyed by turn-id + `POST /agent/turn/{id}/cancel`
  + AbortController); message **copy/edit/retry/branch**; first-run **setup wizard**
  (D3 BYOK).
- **Auth flow fixed** end-to-end (H5). Retire Reflex once parity is reached.

*Verify:* the packaged desktop app launches the sidecar, streams a turn, cancels
mid-stream, edits/retries, and stores the provider key in the OS keychain.

### Phase 4 — Artifacts
- Extend the event protocol with `artifact_open|delta|close|update`; `artifact` +
  `artifact_version` tables; an `artifacts` tool the model uses to create/update
  (str-replace) / rewrite; a **side-panel renderer** (Preview/Code toggle, CodeMirror/
  Shiki) that auto-opens and streams.
- **Sandboxed rendering**: `iframe` `srcdoc` + `sandbox="allow-scripts"` (no
  same-origin) + CSP for HTML; Sandpack for React; Mermaid; DOMPurify for SVG. Copy/
  download; **publish/share** to a standalone sandboxed page; the **analysis tool**
  (QuickJS-in-Worker or Pyodide) with PapaParse/SheetJS.

*Verify:* the model streams an HTML/React/SVG/Mermaid artifact into the panel; versions
step; publish renders standalone under CSP.

### Phase 5 — Extensions parity (MCP · Skills · Plugins)
- **MCP**: add `streamablehttp_client` + `sse_client` transports and **OAuth 2.1**
  (PKCE, Dynamic Client Registration, AS/PR metadata discovery, refresh) via the MCP SDK;
  per-server `env`; **resources** + **prompts** (surfaced in the composer); **per-tool
  permission prompts** (`approval_required` event + reply endpoint to resume a suspended
  turn); `tool_search` deferred loading; **MCPB `.mcpb`** one-click installs; a connector
  **directory** from the official MCP Registry.
- **Skills**: adopt the open **Agent Skills** spec (SKILL.md dirs, YAML frontmatter,
  progressive disclosure, model-driven multi-skill selection); ingest `.skill` packages.
- **Plugins**: replace in-process `plugins/*.py` with **plugin bundles run as stdio MCP
  servers**; a **git-hosted marketplace** (`dulwich`); **hooks** lifecycle
  (SessionStart/UserPromptSubmit/Pre|PostToolUse/Stop) run as sandboxed subprocesses;
  **user slash commands** (`.md` with `$ARGUMENTS`). Enforce enablement at dispatch;
  secrets via keychain.

*Verify:* a remote OAuth MCP server connects and its tools/resources/prompts work; a
`.mcpb` installs in one click; a SKILL.md auto-selects; a PreToolUse hook can block a
call; a marketplace plugin installs from git.

### Phase 6 — Code + Cowork surfaces
- **CLI** `ocd`: `[project.scripts]` entrypoint, Textual/Rich TUI (streamed markdown,
  diff panes, permission statusline), **headless `-p` JSONL** mode, `--max-turns`,
  session resume/fork; **permission modes** + **plan mode**; **subagents/Task tool**
  (nested `run_turn`, restricted tool set, parallel); **checkpoints/rewind** (shadow-git
  snapshots before mutating edits); **CLAUDE.md** hierarchy; repo-scoped tools (ripgrep
  Grep, tree-sitter repo maps, GitPython **worktrees**, PTY `bash` via `pexpect`, OS
  sandbox via bubblewrap/Seatbelt/Podman — completing C2).
- **Cowork**: a **background task engine** (`procrastinate` on the existing Postgres —
  no new broker) decoupled from the SSE connection; **working-folder selection** with a
  scoped-FS sandbox; a **structured task list** the model drives (`task_created`/
  `task_update` events) with live status + HITL steering + stop/pause; a **scheduler**
  (APScheduler) for recurring tasks; **browser automation** via bundled `playwright-mcp`;
  **artifacts-as-files** surfaced from the working folder (`watchfiles`); a task inbox +
  notifications (native / `ntfy`).
- Desktop **Code tab** becomes a real coding-session manager (repo picker, session cards,
  worktree isolation, GUI permission prompts) over the same engine.

*Verify:* `ocd -p` returns JSONL in CI; a plan-mode session gates edits; a subagent runs;
a Cowork task runs in the background against a chosen folder, produces files, and
notifies on completion.

### Phase 7 — Context, memory, quality, evals
- **Context management**: token budgeting, **compaction/summarization** of old turns,
  tool-result eviction, `/compact`, a context meter; prompt caching discipline.
- **Memory**: unify DB `Project.memory` + file memory; **cross-chat memory** (`mem0`);
  **conversation search** (Postgres FTS + embeddings) exposed as a tool; **knowledge
  upgrades** (docling/unstructured ingestion, `chonkie` chunking + overlap, FastEmbed
  embeddings, **hybrid BM25+dense + FlashRank rerank**, KB file management,
  claim-anchored **citations** via `rapidfuzz` span anchoring).
- **Agent quality**: verification-by-re-execution; per-model prompt adaptation; a
  **behavioral eval suite** (`promptfoo`/DeepEval) in CI asserting planning presence,
  parallel-tool emission, error recovery, citation discipline, and context-budget
  adherence.

*Verify:* a long session compacts without losing thread; cross-chat memory recalls prior
facts; hybrid RAG + rerank beats the baseline on a fixture; evals gate CI.

## 6. Cross-cutting concerns

- **Security posture** (local-first, D3): default-deny auth, secrets only in the
  keychain, deny-by-default sandbox for code/bash/working-folders, SSRF + injection
  framing for web content, per-tool HITL permission prompts, no secrets in logs, gitleaks
  in pre-commit + CI. A later **self-hosted server mode** adds `fastapi-users`/OIDC,
  per-user data ownership, and login lockout without touching `ocd_core`.
- **Data portability**: export/import of conversations, projects, and settings;
  local-data reset; backup of the SQLite/Chroma/working-folder tree.
- **Telemetry**: **off by default, opt-in**, local-first; no third-party analytics.
- **Accessibility & i18n**: keyboard-first, ARIA, RTL, screen-reader labels from Phase 3.
- **Releases**: GitHub Releases + `tauri-action` matrix (macOS/Windows/Linux) with signed
  bundles + `latest.json` update feed; `towncrier`/Keep-a-Changelog for the in-app
  "What's new".

## 7. What survives, what changes, what dies

| Verdict | Modules |
|---|---|
| **Survives** (keep + extend) | `agent.py` event protocol + loop mechanics, `mcp_registry.py`, `db/` (models/engine/migrate/Alembic), `conversations.py`, `projects.py`, `knowledge.py` core, `observability.py`, `auth.py` crypto, `util.py`, `sql_guard.py`, the frontend reducer spec in `state.py` (as the TS reference) |
| **Refactored** | `llm.py` → `ocd_core/llm/` (port + adapters); `agent.py` system prompt → Jinja2 sections; `integrations.py` (915 LOC grab-bag) → `tools/`, `connectors/`, `web/`, `sandbox/`; `bigquery.py`+`schema_catalog.py`+`sql_guard.py` → `connectors/bigquery/`; `commands.py`/`skills.py` → Agent-Skills + slash-command registries; config/settings → per-provider + per-conversation |
| **Rebuilt** | the entire **frontend** (Reflex → React/TS + Tauri); the **web search** provider (DDG scrape → SearchProvider port); **artifacts** (new); the **CLI** (new); **Cowork** engine (new) |
| **Deleted** | `app.py`, `.chainlit/`, `chainlit.md`, `run.py`, `schema.sql`, root Windows `requirements.txt` freeze, the `.skill` zip once ingested, `kuzu_db*` dead files, claude.ai-derived theme + hard-coded identity/plan badge |

## 8. Open items for the owner (non-blocking)

1. **LICENSE choice** — MIT (permissive, simplest for a clone) vs Apache-2.0 (adds a
   patent grant). Needed to finish Phase 0.6. *(Default assumption if unspecified: MIT.)*
2. **Product name / branding** — the tree still says "AJ360" and "Open Claude Desktop";
   the shipped product needs an original name + icon set that does not imply Anthropic
   endorsement. Can be decided by Phase 3.
3. **SearXNG dependency** — the best OSS search is self-hosted (AGPL). Acceptable to
   bundle a local SearXNG, or default to the `ddgs` fallback and make SearXNG opt-in?
4. **Rotate the previously-leaked credentials** — the GCP service-account key and
   `.env`/GLM secrets flagged unrotated in the audit are the owner's action at the
   provider; the repo can only prevent recurrence.

None of these block Phase 0, which begins now.

## 9. Independent validation & refinements (multi-agent judge panel)

A structured review workflow drafted **three independent target architectures**
(bias: evolve-Python, TS-rebuild, assemble-OSS) and scored them with a **three-judge
panel** (pragmatic-delivery, long-term-product, parity-fidelity lenses). Result: all
three proposals **independently converged on this document's architecture** — a Tauri
v2 shell + React/TS client over the kept-and-extended FastAPI/`ocd_core` backend, with
the `agent.py:9-37` event vocabulary frozen as the wire contract, the `ocd_core/llm`
BYOK layer kept, and BigQuery demoted to a connector. The panel split **2–1 for the
"hexagonal Python core + TS/React + Tauri" proposal** (the pragmatic-delivery judge
preferred an assemble-OSS variant for faster Code/CLI/Cowork delivery). The winner
equals the owner-locked decisions (D1–D3), so the plan stands. The judges also
confirmed the in-house thin OpenAI-compatible adapter over LiteLLM-as-a-dependency —
validating the Phase 1 choice already shipped.

The following graft-worthy refinements from the losing proposals are **adopted** and
adjust the roadmap ordering above:

1. **Security-before-surface ordering (important).** Land the **interactive HITL
   tool-permission loop** (`approval_required` SSE event + a reply endpoint + dispatch
   enforcement) in an **early phase — before** MCP remote transports/OAuth and Cowork
   working-folder access widen the attack surface. A prompt-injected, tool-enabled
   model is otherwise dangerous the moment remote MCP/Cowork lands. → Pull the HITL
   permission loop out of Phase 5 into **Phase 3/4** (right after stop/cancel).
2. **Don't orphan the one proven capability.** Ship **and validate** a bundled
   **BigQuery MCP connector** in the *same* Phase 2 slice that removes the hard-coded
   BigQuery core tools, so the repo's only end-to-end-proven feature is never dead
   mid-migration.
3. **Context management before Code/Cowork.** The `ContextManager` (per-model
   `tiktoken`/HF tokenizers + tool-result eviction + Claude-Code-style compaction,
   replacing verbatim history concat and the fixed `max_tokens=4096`) is a prerequisite
   for long coding/Cowork turns — move it **ahead of Phase 6**, not into Phase 7.
4. **Multi-user seams from day one (cheap insurance).** Add **nullable
   `owner_id`/`workspace_id`** columns to every table now (inert in local mode), to
   avoid a painful cross-cutting ownership retrofit later.
5. **AgentEngine port + optional coding adapter.** Keep a stable `AgentEngine` port
   (`run(turn) -> AsyncIterator[Event]`) behind the frozen event vocabulary, and ship a
   **minimal native coding-tool floor** (Read/Glob/Grep/Edit over the existing
   `text_editor` jail) early — so the Code/CLI surface delivers value before the full
   substrate, and an OSS coding runtime (OpenCode/Goose) can optionally be dropped in
   later without a new seam. Adopt (don't hand-write) ripgrep/tree-sitter Grep, PTY via
   `pexpect`, worktrees via `dulwich`.
6. **Anthropic-native adapter (additive).** Add an Anthropic adapter behind the same
   `llm` interface (native thinking + `tool_use` blocks) for users who BYO an Anthropic
   key — cheap reasoning-UX insurance, additive to the OpenAI-compatible layer.
7. **BYOK key-bridge invariant.** Project **one** keychain/provider selection onto
   every sub-process (bundled Playwright MCP, any coding sidecar, `code_execution`) so a
   second model-config surface never appears.
8. **Evals as a blocking CI gate — without paid APIs.** Run the agentic-quality evals
   (`promptfoo`/DeepEval) against a **local stub OpenAI-compatible server + Ollama-in-CI**
   so model-agnostic parity/regressions are caught for free (weak/local models silently
   breaking multi-step loops is the key risk).
9. **Standing original-IP audit.** Treat IP-originality as ongoing, not a one-time
   scrub: reword the near-verbatim Anthropic tool-output strings (`integrations.py:812`),
   re-derive the theme, and keep system prompts neutral as features grow.
10. **Frontend cutover de-risking.** Keep the Reflex app runnable behind a flag as an
    executable behavioral spec + contract-test corpus during Phase 3, cutting over
    route-by-route and deleting it only after verified chat parity.
11. **Migration on-ramp.** Ship a `claude_desktop_config.json` importer + `.mcpb`
    one-click install as first-class Phase 4/5 features so existing Claude Desktop users'
    MCP config is portable on day one.
12. **Known bug to fix (P1 finding).** The non-stream fallback in `agent.py` (the
    `_stream_llm` except path) can **re-emit already-streamed text**; fix by tracking
    yielded bytes and emitting only the tail on retry.

## 10. Progress log

- **2026-07-02 — docs:** review + this architecture spec committed.
- **2026-07-02 — Phase 0 (complete):** C1 fail-closed network guard (`netguard.py`),
  C2 bash path-jail, C3 keychain secret store (`secrets.py`), C4 Chainlit retirement,
  C5 real CI + backend Docker/compose, C7 scrubbed prod ids, H1 login rate-limit, H2
  connector SSRF, H6 tool-enablement-at-dispatch; MIT LICENSE. +40 tests.
- **2026-07-02 — Phase 1a (complete):** `ocd_core/llm/` provider layer (12 providers,
  BYOK via keychain, capability catalog, OpenAI-compatible client), `/providers` API,
  zhipuai dependency removed, provider-shape contract tests. Backend suite: 175 passed.
- **2026-07-03 — Phase 1b (complete):** per-turn provider routing (`resolve_turn_client`,
  request+settings `provider`), provider-scoped model fallback, streaming duplicate-emit
  bug fixed, `owner_id`/`workspace_id` multi-user seams (+migration). Backend: 180 passed.
- **2026-07-03 — Ops:** ruff lint debt burned down repo-wide; CI lint gate flipped to
  blocking. Backend 180 + frontend 32 green; `ruff check .` clean.
- **2026-07-03 — Phase 2 (complete):** agent core de-BigQuery'd. New `prompts.py`
  composes a neutral, original general-assistant system prompt from opt-in sections
  (fixes the IP concern + injects today's date); BigQuery demoted to an opt-in connector
  (`bigquery_tools.py`: tool specs + prompt section + `BIGQUERY_ENABLED` flag, auto-on
  when a GCP project is set). The always-on `search_schema`/`run_sql` tools and the
  AJ360 persona are gone from the core. Backend: 187 passed.
- **2026-07-03 — HITL permission loop (complete):** interactive tool-permission gate
  landed *before* remote MCP/Cowork (security-before-surface, §9.1). `permissions.py`
  (modes auto/ask/strict, in-process suspend/resume registry, sensitive-tool policy),
  `approval_required` + `turn_start` SSE events, `POST /agent/turn/{id}/permission` reply
  endpoint, `PERMISSION_MODE`/`PERMISSION_TIMEOUT_SEC` config. Backend: 197 passed.
- **Deferred/refined by §9:** ContextManager before Code/Cowork; AgentEngine port +
  native coding floor; Anthropic-native adapter. BigQuery-connector repackaging as a true
  stdio MCP server (vs the current opt-in built-in tool group) is a tracked follow-up —
  the capability is preserved, not orphaned. HITL registry is in-process (correct for
  local-first); server mode needs a shared channel (Redis) — documented.
- **2026-07-03 — Phase 3 foundation (complete):** new `desktop/` TS/React + Vite client
  + Tauri v2 shell scaffold. The heart is `src/state/transcript.ts` — a pure, framework-free
  `applyEvent` reducer porting the Reflex streaming semantics (thinking coalescing, answer
  streaming, tool-card upsert by id, sources, HITL approval), unit-tested with vitest (8/8).
  Typed SSE+REST+BYOK client (`@microsoft/fetch-event-source`), React binding, chat UI
  (streaming, tool cards, HITL approval prompt, provider/model settings, stop-generation),
  original theme-aware design. Verified: tsc clean, 8 vitest pass, vite build 98 KB gz.
  New CI `desktop` job (typecheck + test + build). Reflex `frontend/` kept as the spec.
- **2026-07-03 — Phase 3 · conversation persistence (complete):** the client now saves &
  restores chats. `persist.ts` losslessly round-trips the rich block transcript through the
  backend's {role,content,kind} store (vitest 5/5); `useConversations` adds the sidebar list,
  create-on-first-send, auto-save on turn-end, open/restore, and delete — all degrading
  gracefully offline. History sidebar UI. Verified: 13 vitest, tsc clean, build 99 KB gz.
- **2026-07-03 — Phase 3 · message actions + shortcuts (complete):** copy-message,
  regenerate/retry-last (truncate-to-last-user + restream, provider-scoped history),
  per-code-block copy button, and app keyboard shortcuts (Esc stops a running turn,
  Cmd/Ctrl+Shift+O new chat). Pure helpers `answerText`/`buildHistory`/`lastUserIndex`/
  `retryFrom` unit-tested. Verified: 16 vitest, tsc clean, build 99.6 KB gz.
- **2026-07-03 — Phase 3 · Artifacts (complete):** the side-panel artifact system, end
  to end. Backend: `artifact_tools.py` (create_artifact/update_artifact specs + prompt
  section + per-turn store), `artifact_open/delta/close` SSE events derived from the tool
  outcome, `artifacts` AgentOptions flag (default on via the route, off for direct callers).
  Frontend: ArtifactDoc transcript handling (open upserts/updates, delta appends, close
  finalizes; `findArtifact`), inline artifact cards, and an `ArtifactPanel` with Preview/Code
  toggle rendering HTML/SVG/Mermaid/React in a **sandboxed iframe** (`sandbox="allow-scripts"`,
  no same-origin, scoped CSP) + copy/download. Verified: backend 202 + 5 artifact tests,
  frontend 18 vitest (open/delta/close + update-upsert + persist round-trip), tsc clean,
  build 101 KB gz.
- **2026-07-03 — Phase 3 · Projects & Knowledge UI (complete):** the Projects surface
  (frontend-only; backend already supported it). Sidebar project selector (General +
  projects + new-project), active-project scoping of the chat list and of turns
  (project_id → per-project instructions + KB), a ProjectPanel with an instructions
  editor, knowledge-file upload/list, and a capacity meter. Pure `conversationsForProject`
  filter unit-tested. Verified: 20 vitest, tsc clean, build 102.6 KB gz.
- **2026-07-03 — Phase 3 · Tauri shell integration (partial — env-gated):** the desktop
  shell is wired: single-instance focus + plugins (global-shortcut, notification, updater,
  opener, os) in `src-tauri/`, updater config (GitHub `latest.json`), capabilities, and a
  `platform.ts` app-side layer (global summon hotkey `CmdOrControl+Shift+Space`, native
  completion notifications) with web fallbacks so the client runs identically in a browser.
  This environment lacks the WebKit system libs, so the Rust cannot be COMPILED here — but
  the full Tauri + 5-plugin dependency graph is validated (`cargo fetch` OK) and the app
  side is fully verified: 23 vitest (3 platform-fallback tests), tsc clean, build 103 KB gz.
- **2026-07-03 — Backend sidecar + release pipeline (complete, verified):** the FastAPI
  backend ships self-contained. `backend/sidecar.py` (uvicorn entry, loopback default via
  netguard, machine-readable ready line) + `ocd-backend.spec` + `build-backend-sidecar.sh`
  freeze it with PyInstaller. **VERIFIED end to end in this environment:** the freeze
  succeeds and the frozen binary (26 MB exe, 290 MB onedir) serves `/healthz` (200) and
  `/providers` (the 12-provider BYOK list) with no system Python. A `release.yml` workflow
  builds the sidecar + Tauri app per-platform (macOS/Windows/Linux) and publishes to
  Releases; the Rust `sidecar()` spawn snippet + `externalBin` wiring are documented (the
  latter kept out of the committed config so UI-only `tauri dev`/`build` still works).
  Backend suite: 204 (2 new sidecar guards).
- **Remaining Tauri work:** system tray, deep links, sign + publish the updater feed, app
  icons, and committing the `externalBin`/`sidecar()` spawn wiring on a build host.
- **2026-07-03 — Usage/cost meter (complete):** a `usage` SSE event at the end of each
  turn (context tokens, output tokens, context limit + %, rough cost) drives a topbar
  context-fill + cost indicator. `ocd_core/usage.py` is dependency-free and offline (a
  ~4-chars/token heuristic — tiktoken was rejected: it fetches its BPE vocab over the
  network, wrong for a packaged offline app) with a best-effort per-model price table.
  Verified: backend 208 (5 new), frontend 24 (1 new), tsc clean, build 103 KB gz.
- **2026-07-03 — MCP remote transports + per-server config (complete, verified E2E):**
  the MCP client now speaks **Streamable HTTP** and **legacy SSE** (not just stdio),
  with per-server **env** vars (merged onto the SDK's safe default env) and remote **auth**
  headers whose bearer token lives in the OS keychain (never mcp_servers.json). Registry
  `_transport_of`/`_server_key`/`_stdio_env` route by transport; `add_mcp_server`,
  `McpBody`, and the route accept url/transport/env/headers/auth_token. Verified with a
  **real in-process FastMCP Streamable-HTTP server**: the registry connects, discovers the
  `echo` tool, and calls it end to end. Backend: 212 (7 new MCP tests).
- **2026-07-03 — Desktop connectors UI (complete):** the client can now manage MCP
  servers — list (name/transport/status/tool-count), add a local **stdio** or remote
  **Streamable-HTTP/SSE** server (with an optional bearer token that goes to the backend
  keychain), add the bundled demo, remove, and toggle per-session enablement; the enabled
  set threads into each turn as `enabled_mcp`. This activates the remote-MCP backend end
  user-side. Verified: 26 vitest (toggle helper), tsc clean, build 104.5 KB gz.
- **2026-07-03 — MCP resources + prompts (complete, verified E2E):** the client now uses
  the full MCP surface, not just tools. Registry `list_resources`/`read_resource`/
  `list_prompts`/`get_prompt`; integrations helpers (graceful [] when a server declares
  none); routes `GET /mcp-servers/{sid}/resources`, `.../resources/read?uri=`, `.../prompts`,
  `POST .../prompts/{name}`. Verified against the FastMCP server: list resources → read
  `greeting://hello` → list prompts → get `summarize`. Backend: 213.
- **2026-07-03 — `.mcpb`/`.dxt` one-click extension installer (complete, verified E2E):**
  the app now installs Claude-Desktop-style extension bundles — a zip with a
  `manifest.json` describing a bundled MCP server. `integrations.install_mcpb` validates
  the manifest + required `user_config`, **rejects zip-slip** path-traversal entries
  before writing anything, unpacks under `extensions/<name>/`, resolves the launch config
  (`${__dirname}`, `${user_config.*}`, `python`→bundled `${PYTHON}`), and registers it via
  the normal `add_mcp_server` path so its tools join the agent's toolset; `remove_mcp_server`
  reclaims the unpacked files (guarded to stay under `extensions/`). `mcpb_manifest_info`
  reads a bundle without installing so the UI can collect `user_config` up front. Routes:
  `POST /mcp-servers/inspect` and `POST /mcp-servers/install` (multipart upload, McpbError→400).
  Frontend: `mcp.inspect`/`mcp.install` (FormData), `useConnectors.install` (prompts for
  required fields), ConnectorsPanel **⬇ Install extension** picker + `extension vX` badge.
  Verified with a **real fixture .mcpb** carrying a stdio FastMCP server: install → unpack →
  connect → discover its `whoami` tool; plus zip-slip/bad-zip/missing-config/uninstall
  safety tests and 5 route tests. Backend: 228 (13 new), frontend: 31 (2 new), tsc clean,
  build 106 KB gz.
- **2026-07-03 — Artifact version history + navigation (complete):** artifacts now keep
  every revision, not just the latest. The transcript reducer records each finalized
  version's content in `ArtifactDoc.versions` on `artifact_close` (pure `setVersion` slot
  writer; `contentAtVersion` reader that tolerates legacy docs without the array), so an
  `update_artifact` no longer discards the prior content. ArtifactPanel gains `‹ vN/M ›`
  navigation that snaps to the newest revision as it streams and lets the user page back
  through history — preview, code, copy, and download all follow the selected version.
  Verified: 34 vitest (3 new — history accumulation, setVersion slotting, legacy tolerance),
  tsc clean, build 106 KB gz.
- **2026-07-03 — Conversation full-text search (complete):** search across every chat's
  title AND message bodies, not just titles. `search_conversations(q, limit)` does a
  portable in-Python scan (identical on SQLite/Postgres) over all threads;
  `_message_text` extracts human-readable text from the JSON block transcripts
  (answer/thinking text, tool summaries, artifact titles+content) so assistant turns are
  searchable; results carry a `snippet` (context window with ellipses) and `matched_in`
  role, ordered pinned/newest-first. Route `GET /conversations/search?q=`. Frontend:
  `conversations.search`; the command palette (⌘K) now fires a debounced content search
  and shows body matches under an **In chats** section (title matches deduped against the
  existing chat list). Verified: 11 backend tests (extraction, title/body match, case-
  insensitivity, snippet windowing, limit, empty/no-match) + a route test; 34 vitest,
  tsc clean, build 107 KB gz. Backend: 237 (11 new).
- **2026-07-03 — Web-search hardening: pluggable provider (complete):** the agent's
  research quality no longer hangs on a single scraped endpoint (a review-flagged
  ToS/reliability risk). A `SearchProvider` seam offers **SearXNG** (privacy-respecting,
  self-hostable, clean JSON API — the recommended free/open-source backend; its URL is
  user-trusted so localhost is allowed and deliberately not SSRF-filtered) with automatic
  fallback to the keyless **DuckDuckGo HTML** endpoint whenever SearXNG is unset or
  unreachable. The HTML/JSON parsers (`_parse_ddg_html`, `_parse_searxng_json`) and result
  normalization (`_result_item`: domain + favicon) are pure and unit-tested against
  fixtures; `_web_results` dispatches via `search_provider`/`searxng_url` settings.
  Frontend: a **Web search** section in Settings (provider dropdown + SearXNG URL);
  `AppSettings`/`SettingsBody` gain the two fields. Verified: 11 web-search tests (parsers,
  dispatch, fallback, non-http rejection, empty query) + settings round-trip — all offline;
  frontend 34 vitest, tsc clean, build 107 KB gz. Backend: 250 (13 new).
- **2026-07-03 — Context compaction for long conversations (complete):** long chats no
  longer risk overflowing the model's context window (which would hard-error at the
  provider). New `ocd_core.context` computes a per-model history budget from
  `catalog.context_window` (50% of the window, floored at 1k tokens; the catalog already
  strips a `provider/` prefix) and `compact_history` keeps as many recent turns as fit,
  drops older ones, and prepends a single deterministic extractive summary note (favoring
  the user's earlier words) recording what was omitted — no extra LLM round-trip on the
  hot path. `run_turn` compacts `history` before assembling messages. History is plain
  role/content turns, so whole-message drops never orphan a tool-call/result pair.
  Verified: 8 tests (unchanged-when-fits, fits-budget-after-compaction, newest-turn-always-
  kept, recap content, window scaling, giant-single-message guard). Backend: 258 (8 new),
  ruff clean.
- **2026-07-03 — MCP OAuth 2.1 (PKCE + DCR), host pieces (complete; interactive step
  pending a build host):** remote MCP servers that require OAuth 2.1 are now supported by
  building on the MCP SDK's `OAuthClientProvider` (full protocol: discovery, Dynamic
  Client Registration, PKCE, silent token refresh — it is an `httpx.Auth`). New
  `ocd_core.mcp_oauth` supplies the host-specific glue: **`KeychainTokenStorage`**
  persists both the issued token and the DCR client registration in the OS keychain (never
  mcp_servers.json), so a connector stays authorized across restarts; **`LoopbackAuthCatcher`**
  is a real one-shot `127.0.0.1` listener that captures the `?code=&state=` redirect
  (the desktop `callback_handler`); `background_provider` attaches stored tokens + refreshes
  silently and raises `ReauthorizationRequired` instead of popping a browser on the backend.
  The registry passes `auth=cfg["auth_provider"]` to `streamablehttp_client`; `_resolve_cfg`
  injects the provider for `auth_mode:"oauth"` servers; `remove_mcp_server` calls
  `clear_oauth`; `list_mcp_servers` surfaces `auth_mode`/`authorized`; route
  `GET /mcp-servers/{sid}/oauth` returns non-secret status. Verified offline (no live OAuth
  server needed): token/client-info round-trips, corrupt-read tolerance, clear/has/summarize,
  DCR client metadata (public client, PKCE, refresh grant), provider is an httpx.Auth,
  `_resolve_cfg` injection, and the **loopback catcher end-to-end** (real HTTP GET →
  code+state recovered). Backend: 269 (11 new). *Remaining:* the interactive browser
  authorize + connect-retry loop is wired but only E2E-verifiable on the Tauri build host
  against a live OAuth MCP server.
- **2026-07-03 — RAG upgrade: smart chunking + citations (complete):** knowledge
  retrieval quality is materially better. Ingestion now uses `chunk_text` — paragraph→
  sentence→hard-wrap, boundary-aware with carried overlap so a chunk rarely cuts a
  sentence and a fact spanning a boundary stays findable (every chunk ≤ size, guaranteed)
  — replacing the old fixed 2000-char windows with no overlap. Retrieval gains attribution:
  `search_project_kb_sources` returns `[{source, chunk, text, score}]` (score = 1−cosine
  distance) and `search_project_kb` heads each passage with `[source · chunk N]`, so the
  cited context flows into the agent's retrieval block; a new operating principle tells the
  model to attribute facts to their named source. Verified with a **real Chroma ingest→
  search round-trip** asserting citations, plus pure chunker tests (short/empty, size+
  overlap, giant-paragraph hard-split, paragraph-boundary preference). Backend: 274 (5 new),
  ruff clean.
- **2026-07-03 — Conversation export (Markdown + JSON) (complete):** any chat can be
  saved out. Pure serializers in `exportConversation.ts`: `toMarkdown` renders `## You` /
  `## Assistant` turns with thinking collapsed in `<details>`, tool calls noted as
  blockquotes, and artifacts embedded as fenced code with their version; `toJSON` emits a
  versioned structural envelope; `exportSlug` makes a safe filename. A header ⬇ button (shown
  only when the chat is non-empty) downloads the current conversation as Markdown. Verified:
  8 vitest (headings, content, thinking/tool rendering, artifact fences, empty-turn skip,
  trailing-newline hygiene, JSON envelope, slug). Frontend: 42 vitest, tsc clean, build 108 KB gz.
- **2026-07-03 — Composer slash-command skill autocomplete (complete):** Agent Skills are
  now discoverable + invocable from the UI (they already auto-activate server-side via
  `resolve_skill`→`matching_skill`; this closes the discovery gap). Typing `/` opens a
  keyboard-navigable dropdown of matching skills; selecting one prefills `/name `. Pure
  `slashSuggestions(skills, text)` (subsequence match on name/description; suppresses once a
  space commits the command) + `applySlash`; new `skills` API + `useSkills` hook feed the
  Composer. Verified: 6 vitest for the filter (not-a-slash, bare-slash lists all, name/desc
  match, committed-command suppression). Frontend: 48 vitest, tsc clean, build 108 KB gz.
- **2026-07-03 — Theme: light/dark/system toggle (complete):** the previously-unused
  `theme` setting now drives a real switch. Pure `resolveTheme(pref, systemDark)` +
  `nextTheme` (cycles system→light→dark) + `themeGlyph`; `useTheme` stamps
  `data-theme` on `<html>`, follows the OS via `matchMedia` while on "system", and persists
  the preference to settings. CSS gains `:root[data-theme="dark"]` (beats the media query
  by specificity) plus a `:not([data-theme])` pre-JS fallback that still honors the OS on
  first paint. A topbar glyph button (◐/☀/☾) cycles the preference. Verified: 10 vitest
  (explicit-wins, system-follows-OS, cycle order, glyph labels, type guard). Frontend: 53
  vitest, tsc clean, build 108 KB gz.
- **2026-07-03 — Sidebar rename + pin conversations (complete):** the backend's rename +
  setPinned (PATCH conversation) are now reachable from the UI. Each sidebar row gains
  pin/unpin (★/☆) and rename (✎) actions beside delete; `useConversations.rename` /
  `togglePin` call the API and refresh so pinned chats sort to the top. Verified: frontend
  53 vitest (unchanged; UI wiring over already-tested pure helpers), tsc clean, build 108 KB gz.
- **2026-07-03 — Auto-title conversations (complete):** chats now get a concise generated
  title after their first exchange (Claude behavior), replacing the truncated-first-message
  default. When a turn goes idle and `isFirstExchange(messages)` holds (exactly one user +
  ≥1 assistant), `useConversations` calls the backend LLM titler once per conversation
  (`POST /conversations/title`, which itself falls back to the truncated first message on
  any error/keyless env) and renames. Guarded by a `titled` set so it fires exactly once.
  Verified: 5 new vitest for the pure guards (`isFirstExchange` before/after reply, second
  user message, empty; `firstUserText`). Frontend: 58 vitest, tsc clean, build 109 KB gz.
- **2026-07-03 — Tool-result truncation (complete):** a single oversized tool output (a
  large web page, SQL dump, or MCP payload) can no longer overflow the model's context
  window. `context.truncate_tool_result(text, max_chars=8000)` caps a result to ~2k tokens
  keeping the head + tail (both usually carry the signal) with a middle notice stating how
  many characters were dropped; `run_turn` applies it where it appends each `tool` message.
  Complements the history compaction. Verified: 4 new tests (short passthrough, head+tail
  preserved under cap, omitted-count accuracy). Backend: 278 (4 new), ruff clean.
- **2026-07-03 — Retry transient provider errors with backoff (complete):** BYOK users on
  free tiers hit rate limits constantly; previously any error fell back or failed at once.
  `_is_retryable` classifies transient failures (status 408/409/425/429/5xx, or name hints
  like RateLimit/Timeout/Connection/Overloaded) vs permanent (400/auth); `_create_with_retry`
  retries the chosen model with exponential backoff (2 retries, 0.5s→1s) before `_llm_create`
  falls back to the provider's default model. Verified with a fake client + patched sleep:
  classifier by status and by name, retryable-then-success, non-retryable-raises-immediately,
  exhaustion, and fall-back-after-retries. Backend: 283 (5 new), ruff clean. *(Covers the
  non-streaming planning/verification passes; streaming-path retry is future work.)*
- **2026-07-03 — Empty-state starter prompts (complete):** a fresh chat now offers curated,
  model-agnostic suggestion chips (draft email, explain, debug, chart, summarize, brainstorm);
  clicking one sends it. `STARTER_PROMPTS` is a pure export (2 vitest: well-formed + unique
  labels). Frontend: 60 vitest, tsc clean, build 109 KB gz.
- **2026-07-03 — Composer text-file attachments (complete):** users can attach text files
  (.txt/.md/.csv/.json/code/…) to a message via a 📎 button; files are read client-side,
  size-clamped, shown as removable chips, and inlined into the outgoing message as named
  fenced context blocks — model-agnostic (no vision required), so it works with any BYOK
  model. Pure `formatAttachments`/`withAttachments`/`clampContent`/`fenceLang` helpers.
  Verified: 8 vitest (clamp, lang mapping, block formatting, combine with/without text).
  Frontend: 68 vitest, tsc clean, build 110 KB gz.
- **2026-07-03 — Keyboard shortcuts help modal (complete):** pressing `?` (ignored while
  typing in any input/textarea/contenteditable — it's a printable char) opens a modal
  listing the app's shortcuts (⌘K palette, ⌘⇧O new chat, Enter/⇧Enter, `/` skills, Esc,
  `?`), also reachable from the command palette. Driven by a pure `SHORTCUTS` registry +
  `isEditableTarget` guard. Verified: 4 vitest (registry well-formed + unique keys, palette
  shortcuts present, editable-target detection true/false cases). Frontend: 72 vitest, tsc
  clean, build 110 KB gz.
- **2026-07-03 — Auto-scroll transcript + jump-to-latest (complete):** the transcript now
  follows streaming content instead of stranding the user mid-answer. `useAutoScroll` (pure
  `isNearBottom` helper) keeps the view pinned to the bottom as messages/tokens stream while
  the user is already near the bottom, and surfaces a floating ↓ jump-to-latest button when
  they've scrolled up to read. Verified: 4 vitest (`isNearBottom` at bottom / within / beyond
  threshold, custom threshold). Frontend: 76 vitest, tsc clean, build 110 KB gz.
- **2026-07-03 — Expanded model catalog (complete):** BYOK users get more open models out
  of the box. The previously-empty `models` lists for OpenRouter / Together / Groq / Mistral
  are now populated (Llama 3.3, DeepSeek-V3, Qwen2.5-72B, Mixtral, Gemma 2, Codestral, …) and
  Qwen / Ollama expanded (incl. QwQ, deepseek-r1). Added a catalog-integrity test: every
  hosted provider offers a model list containing its default_model. The Settings picker
  renders these automatically. Backend: 285 (2 new), ruff clean.
- **Next (Phase 3 cont.):** interactive OAuth authorize on the Tauri host;
  true artifact token-streaming; finish the Tauri shell on a build host (tray, icons,
  signed updater, commit externalBin/sidecar spawn).
