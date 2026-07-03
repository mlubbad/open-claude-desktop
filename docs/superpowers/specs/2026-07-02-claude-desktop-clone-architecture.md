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
- **Next (Phase 3 cont.):** MCP OAuth 2.1 (PKCE + DCR) + resources/prompts + `.mcpb`
  one-click installs + a connectors UI in the new client; artifact version history + true
  token-streaming; message edit/branch; command palette; finish the Tauri shell on a
  build host (tray, icons, signed updater, commit externalBin/sidecar spawn).
