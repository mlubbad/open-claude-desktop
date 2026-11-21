# Full Repository Review — VersoWork

> **Date:** 2026-07-02 · **Branch:** `claude/claude-desktop-clone-review-2ezbwf`
> **Method:** A multi-agent review — 7 parallel subsystem readers (every source file
> read) + 12 Claude-Desktop-parity gap analysts + a completeness critic — followed by
> a first-hand read of the load-bearing modules (`agent.py`, `llm.py`, `app/main.py`,
> `routes/agent.py`, `api_client.py`). Every finding below is grounded in a real
> `file:line` reference verified against the working tree.
> **Mission context:** evolve this repo into an open-source, **model-agnostic**
> ("bring your own key / open models") clone of Anthropic's Claude Desktop at full
> functional parity — Chat, Projects, Memory, Artifacts, Code, Cowork, MCP, Plugins,
> Skills, CLI, desktop shell — where the *only* deliberate difference from Claude
> Desktop is the model backend. Functional/UX parity is the goal; proprietary
> Anthropic code, assets, branding, and verbatim system prompts are **not** copied.

---

## 1. Executive summary

The repository is a **genuinely well-engineered Python codebase that is roughly 65% of
a model-agnostic agent platform**, but it is (a) **welded to a single domain**
(Google BigQuery / "Analytics" analytics), (b) **locked to a single model provider**
(Zhipu GLM via the `zhipuai` SDK), (c) **still shipping the wrong surface** (the legacy
Chainlit `app.py`, which the documented refactor was supposed to retire), and (d)
carrying **several critical security holes** in its default configuration.

The bones are strong. `backend/ocd_core/agent.py` is a clean, UI-agnostic ReAct loop
with a typed streaming event protocol that is a real Claude-Desktop-grade foundation.
`mcp_registry.py` is a solid MCP client. The FastAPI backend is genuinely thin, with a
Postgres/SQLModel/Alembic persistence layer, ChromaDB RAG, a rotating audit log, and a
rate limiter. The team's spec/plan discipline (in `docs/`) is exceptional.

But to become the product the mission describes, four things must change in order:
**stop the bleeding** (security + ship the right app), **insert a model-provider
abstraction** (the headline differentiator, which does not exist yet), **de-specialize
the agent** (BigQuery becomes an optional connector), and **rebuild the client** in
TypeScript/React inside a Tauri desktop shell (the current Reflex UI cannot reach the
parity bar for artifacts, streaming smoothness, or a native shell).

### Decisions taken (owner-confirmed, 2026-07-02)
1. **Frontend/shell:** rebuild the UI in **React/TypeScript inside a Tauri v2** desktop
   shell; keep the Python backend as a bundled sidecar.
2. **BigQuery domain:** **demote to an optional built-in connector** — the
   general assistant is the product.
3. **Form factor:** **local-first desktop, single user**, OS-keychain secrets; a
   self-hosted multi-user server mode is a later, additive option.
4. **Execution:** commit this review + the architecture/roadmap spec, then begin
   **Phase 0 security + ops hardening** immediately.

---

## 2. What exists today (verified inventory)

| Layer | Location | State |
|---|---|---|
| **Legacy chat app** | `app.py` (2,816 lines), `.chainlit/`, `chainlit.md`, `run.py`, `schema.sql` | Chainlit "god module". **Still the shipped surface** (Dockerfile CMD + compose). Was meant to be deleted in refactor Phase 5. |
| **Domain core** | `backend/ocd_core/` (~3,570 LOC, 24 modules) | The framework-agnostic single source of truth. High quality. **BigQuery/provider-coupled.** |
| **HTTP/SSE API** | `backend/app/` (`main.py`, `deps.py`, `schemas.py`, `sse.py`, 12 routes) | Thin, well-designed REST + SSE surface over `ocd_core`. **Fails open to `anonymous`.** |
| **Frontend** | `legacy_frontend/` (Reflex, `state.py` 1,207 lines, 11 components) | Python→React thin client. Faithful streaming UX reimplementation, but Reflex ceiling + auth token never forwarded. |
| **Persistence** | `backend/ocd_core/db/` (SQLModel + Alembic) | Projects + Conversations in Postgres; idempotent JSON→PG migration. Good. |
| **Extensions** | `plugins/*.py`, `skills/*.md` + `.skill` zip, `mcp_servers/`, `connectors.json`, `mcp_registry.py` | Four ad-hoc mechanisms. MCP client is stdio+tools-only. Not the open Agent Skills / MCPB formats. |
| **Ops** | `.github/workflows/ci.yml`, `Dockerfile`, `docker-compose.yml`, `.pre-commit-config.yaml` | CI runs only 3 legacy tests (red); Docker builds the wrong app and **fails on Linux**; no LICENSE. |
| **Docs** | `docs/architecture-audit.md`, `docs/superpowers/{specs,plans}/` | 6 specs + 4 large TDD plans. Excellent discipline; Phases 1–4 done, **Phases 5–6 not executed.** |

---

## 3. Strengths worth preserving

These are the assets the refactor should **keep and build on**, not rewrite:

1. **The typed streaming event protocol** (`backend/ocd_core/agent.py:9-37`). Region
   framing (`think_open`/`think_close`/`answer_open`/`answer_to_think` with
   `phase`+`elapsed`), scoped token deltas (`delta{scope:answer|think}`), id-keyed tool
   lifecycle (`tool`/`tool_result`/`tool_error`/`table`/`sources`), terminal `done`.
   Served 1:1 as SSE by `backend/app/sse.py` and consumed verbatim by the frontend.
   This is a genuine Claude-Desktop-class streaming contract and should be **extended**
   (artifacts, todos, approvals, usage), never replaced.
2. **The agent loop mechanics** (`agent.py:541-718`): up-front tool cards for parallel
   calls, `asyncio.as_completed` execution, results re-keyed by `tool_call_id`,
   never-raise tool outcomes that return `"fix and retry"` strings (Claude's `is_error`
   protocol), a blocking-SDK-stream→async bridge (`agent.py:270-301`), model fallback,
   and non-stream fallback.
3. **The MCP client registry** (`mcp_registry.py`): one persistent `ClientSession` per
   server on a dedicated event-loop thread, per-call timeouts that tear down broken
   sessions, drop/respawn, `atexit` cleanup, real integration tests.
4. **Persistence + migration** (`db/`): SQLModel models, Alembic, an idempotent,
   backed-up filesystem→Postgres migration with fidelity tests.
5. **The frontend behavioral spec** (`state.py:936-1148`): thinking-block coalescing
   with elapsed labels, `answer_to_think` folding, tool-card upsert-by-id, source rows.
   This is a **framework-independent reducer spec** that ports directly to the new
   TypeScript client.
6. **The compounding knowledge-wiki idea** (legacy `app.py`: seeded gotchas,
   `/learn-finding` with cheap-model structuring, `/lint-knowledge` staleness): an
   original memory mechanism worth salvaging into the model-agnostic core.
7. **Test + spec culture**: hermetic fixtures (in-memory SQLite), guard tests proving
   rejected SQL never builds a client, a threaded Chroma race test, architecture
   regression guards (`test_no_duplication.py`, `test_packaging.py`), and dated design
   specs with locked-decision tables and TDD plans.

---

## 4. Critical findings (fix first)

Ordered by severity. All verified against the tree.

### 🔴 C1 — Unauthenticated remote code execution (fail-open auth + command-exec route)
`backend/app/deps.py:10-14` returns the user `"anonymous"` for **every** request
whenever `APP_USERNAME`/`APP_PASSWORD`/`APP_AUTH_SECRET` are unset — which is the
**out-of-the-box default** (`ocd_core/auth.py:44-46`). Meanwhile `POST /mcp-servers`
(`routes/integrations.py:63-65` → `ocd_core/integrations.py:287-296`) **registers and
immediately executes an arbitrary stdio command**. Net effect: a default deployment
bound to any network is an unauthenticated RCE. **Fix:** default-deny (or a
locally-generated token on first run), and never let the exec path run under
`anonymous`.

### 🔴 C2 — `bash` tool sandbox escape via absolute paths
`run_bash` (`ocd_core/integrations.py:696-711`) blocks `..` and shell metacharacters
and sets `cwd` to `_sandbox`, but **absolute-path arguments pass**: `cat /etc/passwd`,
`cat /home/user/open-claude-desktop/.env`, `find / ...` all succeed → host filesystem
read + exfiltration chain. **Fix:** run under an OS sandbox (bubblewrap/Podman on
Linux, Seatbelt on macOS) or resolve+jail every path argument to the session root.

### 🔴 C3 — Plaintext secrets in a git-tracked file
`add_connector` writes `header_value` (Authorization / API-key values) verbatim into
`connectors.json` at the repo root (`integrations.py:99,124-138`). Same anti-pattern
will bite BYOK provider keys. **Fix:** OS keychain (`keyring`) with an encrypted-file
(`cryptography` Fernet) fallback for headless installs; never persist secrets to
tracked JSON.

### 🔴 C4 — The shipped app is the legacy Chainlit surface (Phase 5 never happened)
`Dockerfile:21` CMD is `chainlit run app.py`; `docker-compose.yml` auto-loads
`schema.sql` and runs the Chainlit container; `README.md:63` documents it. The real
two-service app (FastAPI + Reflex) has **no** container/compose/CI path. Worse, this
creates a **split-brain data store**: `app.py` writes projects to
`projects/_registry.json` while the backend writes Postgres — same IDs, data-loss
vector. **Fix:** execute the promised Phase 5 retirement (delete `app.py`, `.chainlit/`,
`chainlit.md`, `schema.sql`, `run.py`; drop the `chainlit` extra) and repoint
Docker/compose/CI at the two-service app.

### 🔴 C5 — CI is green-theater; Docker build fails on Linux
`ci.yml:20` runs bare `pytest` from the repo root; root `pyproject.toml:41` sets
`testpaths=["tests"]`, so CI collects **only the 3 legacy tests** — and one of them
(`tests/test_auth.py:23`) loads a path that moved in the refactor, so the collected job
is **red**. The 37 backend + 4 frontend tests never run. `Dockerfile:11-12` installs a
Windows `pip freeze` (`requirements.txt:148` pins `pywin32==312`), which **has no Linux
wheel** → the image build errors. **Fix:** per-service CI matrix that installs each
package and runs its real suite; a Linux-clean dependency set.

### 🔴 C6 — Provider lock-in: the model layer is a hard-coded singleton (blocks the mission)
`ocd_core/llm.py:17-23` is a lazy global `ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))`
whose docstring says "do NOT change the logic." `agent.py`, `conversations.py:135-148`,
and `integrations.py:485-491` all bind to it and to the `zhipuai` SDK shape. There is
**no provider abstraction, no BYOK, no local-model support, no per-conversation model,
no usage/cost tracking**. This is the single biggest gap between the repo and its stated
mission. **Fix:** a `ChatClient` port with OpenAI-compatible + Anthropic-compatible
adapters (Phase 1).

### 🔴 C7 — Leaked third-party production infrastructure still committed
`.env.example:13,51-53` contains a real Al Jazeera **production** GCP project id, GCS
bucket, and service-account email; the docs still flag the previously-leaked SA key /
`.env` GLM secrets as **unrotated**. **Fix:** scrub real identifiers from
`.env.example`; the owner must rotate the leaked credentials at the provider.

---

## 5. High-severity findings

- **H1 — Login has no rate limit / lockout** (`routes/auth.py:13-17`): the sliding-window
  limiter exists but is wired only to `/agent/turn`. A 7-day-TTL token means one
  unlimited brute-force gate. Add `slowapi`/limiter on `/auth/login`.
- **H2 — SSRF via connectors** (`routes/integrations.py:41-44`, `integrations.py:150-161`):
  `POST /connectors` accepts any `base_url`; `/connectors/{id}/test` makes the server GET
  it (with the stored auth header, following redirects) and **skips** the `_blocked_host`
  guard that `web_fetch` uses. Reuse the SSRF guard; strip auth on cross-origin redirect.
- **H3 — Stored XSS in the legacy Projects dashboard** (`app.py:1890-1894` under
  `unsafe_allow_html=true`): interpolates project name + instructions first line into raw
  HTML without escaping. Retired with C4.
- **H4 — Dataset-scope SQL enforcement exists ONLY in legacy `app.py`** (`app.py:956-962`)
  and was **not** ported to the backend `bigquery.py`. When BigQuery becomes a connector,
  port the scope check with it.
- **H5 — Frontend never forwards the session token** (`api_client.login` at
  `api_client.py:78-83` is only called by tests): the login gate is decorative and any
  auth-enabled deployment breaks. Fixed by the new client's auth flow (Phase 3).
- **H6 — Tool-enablement is advisory only** (`integrations.py:387-392`): `enabled_*` lists
  gate only which schemas are *shown* to the model; `run_tool` dispatches any registered
  tool by name, so a hallucinated/injected tool call still executes. Enforce enablement at
  dispatch.
- **H7 — CORS `allow_credentials=True` with wildcard methods/headers** (`app/main.py:31-39`).
  Tighten for any networked deployment.

---

## 6. Medium/architectural findings

- **M1 — No context-window management.** `agent.py:554-557` concatenates system + full
  history + goal every turn; up to 16 steps of large tool results (24k-char web fetches,
  50-row JSON tables) accumulate with **no token counting, compaction, or eviction** and a
  fixed `max_tokens=4096`. Long turns overflow any model opaquely.
- **M2 — Self-verification cannot catch wrong numbers.** The Max-effort verify pass
  (`agent.py:690-718`) asks the model to re-read its own prose; parity needs
  verification-by-re-execution.
- **M3 — Monolithic system prompt.** `agent.py:157-190` is a single Analytics/BigQuery persona
  f-string; there is no composable section architecture and no user-profile slot (identity
  is hard-coded — `"Mohammed"` at `home.py:22`/`sidebar.py:65`, a fake `"Max"` plan badge,
  a claude.ai-derived theme — all of which are also IP concerns to replace).
- **M4 — Web tools are fragile/insecure.** Search is a keyless DuckDuckGo HTML **scrape**
  (`integrations.py:398,436-448`, ToS-risky, silently breaks on markup drift); the SSRF
  guard has a DNS-rebinding TOCTOU (`getaddrinfo` then a second independent resolve at
  fetch); favicons are fetched from Google's S2 service (leaks browsed domains); fetched
  content is not framed as untrusted (prompt-injection surface); `web_fetch` rejects PDFs
  and the sub-query expander is provider-locked to `zhipuai`.
- **M5 — RAG quality.** Fixed 2000-char chunks, no overlap, default Chroma embedding,
  `top_k=5`, no hybrid/keyword retrieval, no reranking; only PDF/CSV(header+20 rows)/text
  ingestion; no delete/download/preview of KB files; the capacity meter is not enforced on
  upload (unbounded read into RAM).
- **M6 — Two disconnected memory stores.** DB `Project.memory` (a dead store nothing writes)
  vs `agent_memory/<pid>` files (the `memory` tool) never sync; no cross-chat memory
  pipeline.
- **M7 — Anthropic-derived text/phrasing to replace.** The theme replicates claude.ai's
  palette; `memory` tool output strings track Anthropic's published wording; the plan badge
  copies Anthropic plan naming. All must be re-originated for an independent OSS product.

---

## 7. Claude-Desktop parity gap map

Twelve dimensions analyzed. `●` present · `◐` partial · `○` missing. "Effort" is to reach
parity in that dimension.

| Dimension | State | Effort | The gap in one line |
|---|:--:|:--:|---|
| **Chat UX** | ◐ | XL | Streaming + thinking display are close; **no** stop, edit/retry/branch, attachments, search, styles, shortcuts, i18n, voice. |
| **Projects / Knowledge / Memory** | ◐ | L | Projects + RAG exist; **no** cross-chat memory, context-stuffing, hybrid retrieval, KB management, conversation search. |
| **Artifacts** | ○ | XL | **None.** No artifact events, storage, side-panel renderer, sandboxed preview, publish/share, or analysis tool. |
| **Code (CLI + Code tab)** | ○ | XL | **No CLI at all**; the "Code" tab is a BigQuery SQL console. No permission modes, plan mode, hooks, subagents, checkpoints, worktrees. |
| **Cowork** | ○ | XL | Cosmetic tab only. No background task engine, working-folder sandbox, task lists, scheduler, browser automation. |
| **MCP / Connectors** | ◐ | XL | Solid stdio client; **no** remote (HTTP/SSE) transport, OAuth, resources, prompts, per-tool permission prompts, MCPB installs, directory. |
| **Plugins / Skills** | ◐ | L | Ad-hoc `*.py`/`*.md`; adopt the **open Agent Skills + MCPB specs**, marketplace, hooks, user slash commands. |
| **Model / Provider layer** | ○ | L | **The differentiator, and it's missing.** One hard-coded GLM singleton; no BYOK, catalog, capability detection, cost, caching, local models. |
| **Desktop platform** | ○ | XL | Two localhost servers; **no** shell, tray, global hotkey, auto-update, OS keychain, deep links, notifications. |
| **Agent quality** | ◐ | XL | Good bones; **no** structured planning/todos, subagents, context management, HITL permissions, verification-by-re-execution, evals. |
| **Onboarding / accounts** | ○ | L | **No first-run wizard** (blocks BYOK), no user profile/preferences, fail-open default, decorative login. |
| **Built-in web tools** | ◐ | M | DDG scrape + basic fetch; needs a real search provider, robust extraction, inline citations, injection framing, provider-agnostic sub-queries. |

**Additional uncovered areas flagged by the critic** (folded into the roadmap):
sharing/collaboration, data portability/backup/export, telemetry/privacy/retention,
accessibility, mobile/web companion, offline resilience, self-host ops, usage-limits UX,
and safety/prompt-injection hardening.

---

## 8. The recommended open-source stack (all free/OSS unless noted)

Every gap analyst independently converged on this toolkit. Licenses verified.

**Model layer:** `openai` SDK (Apache-2.0) as the base of a thin hand-rolled adapter
covering Zhipu/DeepSeek/Qwen/OpenRouter/Ollama/vLLM/LM Studio via `base_url`; `anthropic`
SDK (MIT) as an optional second adapter (native thinking + `cache_control`); LiteLLM (MIT)
evaluated as the alternative; `models.dev` + LiteLLM metadata JSON for the model catalog;
`tiktoken` (MIT) for token counting; `json-repair` (MIT) for weak-model tool args;
`tenacity` (Apache-2.0) for retries.

**Secrets:** `keyring` (MIT) OS-native store; `cryptography` Fernet (Apache-2.0/BSD)
encrypted-file fallback; `argon2-cffi` (MIT) for optional local passwords.

**Frontend + shell:** React 18 + TypeScript + Vite (MIT); `assistant-ui` (MIT) for chat
primitives (streaming, edit, retry, branch nav); `@microsoft/fetch-event-source` (MIT) for
cancellable SSE; `react-markdown`+`remark-gfm`+KaTeX (MIT); Shiki (MIT) highlighting;
TanStack Virtual (MIT) transcript virtualization; Radix UI + Tailwind (MIT); `cmdk`+`tinykeys`
(MIT) command palette/shortcuts; `i18next` (MIT); **Tauri v2** (MIT/Apache-2.0) shell with
first-party tray/global-shortcut/updater/deep-link/notification/single-instance/keychain
plugins; PyInstaller/Briefcase to freeze the FastAPI backend as a Tauri sidecar;
`platformdirs` (MIT) + SQLite for local-first storage.

**Artifacts:** native sandboxed `iframe` (`srcdoc` + `sandbox="allow-scripts"` + CSP);
Sandpack (Apache-2.0) for React artifacts; Mermaid (MIT); DOMPurify (Apache/MPL) for SVG;
CodeMirror 6 (MIT) code view; QuickJS-emscripten (MIT) or Pyodide (MPL-2.0) for the analysis
tool; `jsdiff` (BSD) for version diffs; PapaParse/SheetJS-CE for data files.

**MCP / extensions:** the official `mcp` Python SDK (MIT) — already a dependency — provides
`streamablehttp_client`/`sse_client` transports + OAuth 2.1 helpers; MCPB spec/toolchain
(`anthropics/mcpb`, MIT) for `.mcpb` one-click installs; the official MCP Registry (MIT, free
API) for the connector directory; the open **Agent Skills** spec (implement independently);
`python-frontmatter`+PyYAML (MIT); `jsonschema` (MIT) for manifest validation; `dulwich`
(Apache-2.0) for the git-hosted marketplace; `watchdog` (Apache-2.0) hot-reload.

**Code / Cowork:** `procrastinate` (MIT) Postgres-backed task queue (no new broker);
APScheduler (MIT) for schedules; bubblewrap (LGPL) / Podman (Apache-2.0) / macOS Seatbelt for
the working-folder sandbox; Playwright + `playwright-mcp` (Apache-2.0) browser automation;
ripgrep + `py-tree-sitter` (MIT) for repo tools/maps; GitPython/`dulwich` for worktrees;
`pexpect`/`ptyprocess` (ISC) persistent PTY shells; Textual + Rich (MIT) for the CLI TUI;
`watchfiles` (MIT); `ntfy`/`apprise` for notifications.

**Knowledge / memory:** `docling` (MIT) or `unstructured` (Apache-2.0) document conversion;
`chonkie` (MIT) chunking; FastEmbed (Apache-2.0) local embeddings; keep ChromaDB + `rank-bm25`
(Apache-2.0) hybrid; FlashRank (Apache-2.0) reranking; `mem0` (Apache-2.0) cross-chat memory;
Postgres FTS for conversation search; `rapidfuzz` (MIT) for citation span anchoring.

**Web tools:** SearXNG (AGPL, self-hosted) primary search; `ddgs` (MIT) fallback; `trafilatura`
(Apache-2.0) extraction; `pypdf` (BSD) PDF fetch; Protego (BSD) robots.txt; optional BYO-key
Brave/Tavily (free tiers) behind the same interface.

**Quality / evals:** `promptfoo` (MIT) or DeepEval (Apache-2.0) agent-behavior evals in CI;
`respx` (BSD) for provider-shape contract tests; Jinja2 (BSD) for prompt composition; Pydantic
v2 (MIT) discriminated-union event types.

---

## 9. How this maps to the build plan

The companion document
[`docs/superpowers/specs/2026-07-02-claude-desktop-clone-architecture.md`](../superpowers/specs/2026-07-02-claude-desktop-clone-architecture.md)
turns this review into a target architecture (Ports & Adapters for providers/tools/search/
sandbox, a Strategy-based model registry, an extended typed event protocol, an event-sourced
transcript) and an **8-phase roadmap** (0–7), each phase leaving a working app with green
tests. Phase 0 — the security + ops hardening enumerated in §4/§5 — begins immediately and
depends on none of the larger decisions.
