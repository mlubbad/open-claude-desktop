# Harness v1 — Agentic Coding Core — Design

> **Status:** Approved by user 2026-07-20 (all sections). **Line:** `origin/main` (branch `feat/harness`, base `373580f`).
> **Scope:** v1 = agentic coding core on local folders; full Claude-Code parity tracked as a phased roadmap (P2–P4, §14).

## 1. Context & goal

"Harness" is the machinery around the model — the ordinary code that handles tool
execution, permissions, planning, memory, and safety while the model only decides the
next step. Claude Code's capability lives mostly in this machinery, not the model.
This design brings that machinery to open-claude-desktop.

The product already has a real agentic substrate on `origin/main`:

| Exists today | Where |
|---|---|
| Streaming multi-provider tool loop (effort-capped iterations, plan/verify stages) | `backend/ocd_core/agent.py` (`run_turn`, `_run_one_tool`, `_stream_llm`) |
| HITL permission gate (`auto`/`ask`/`strict`, fail-closed, audited, suspends turn) | `backend/ocd_core/permissions.py` + `POST /agent/turn/{turn_id}/permission` + `desktop/src/components/ApprovalPrompt.tsx` |
| Background agent tasks with persisted event transcripts | `backend/ocd_core/cowork.py` + `CoworkPanel.tsx` |
| Skills (frontmatter + auto-trigger + repo/zip import), slash commands | `backend/ocd_core/skills.py`, `commands.py` |
| MCP registry + OAuth, connectors, plugins | `mcp_registry.py`, `mcp_oauth.py`, `integrations.py` |
| Deterministic history compaction + tool-result truncation | `context.py` |
| Track-2 egress safety (SSRF DNS pinning, first-contact domain approval, secret redaction) | `egress*.py`, `docs/track2-local-agent-safety-plan.md` |
| Job queue, scheduler, workspaces/tenancy, observability audit trail | `jobqueue.py`, `scheduler.py`, `tenancy.py`, `observability.py` |

What is missing versus Claude Code's harness: a workspace-scoped **file tool suite**,
**rule-based permissions with modes**, **checkpoints/rewind**, a **model-driven plan
tool**, **environment context assembly**, and (later phases) **hooks**, **generalized
subagents**, **memory hierarchy**, and an **opt-in sandbox**. Closing those gaps —
starting with the coding-on-local-folders workload — is this feature.

### Decisions log (user-approved 2026-07-20)

1. **Scope:** v1 = agentic core; full Claude-Code parity phased (P1–P4), tracked here.
2. **Line:** design and build against `origin/main` (not the local de-AJ360/Google-auth fork).
3. **V1 workload:** coding on local folders (Cowork-centered), per the three studied
   harness articles (LogRocket pipeline harness, dailydoseofds CrewAI rebuild,
   shareAI-lab learn-claude-code) and Claude Code's own documented architecture.
4. **Approach:** extend the native `run_turn` loop (no Claude Agent SDK embed — it is
   Claude-models-only and would discard the multi-provider layer and Track-2 hardening;
   no ACP transport in v1 — but event naming stays ACP-shaped so a later adapter is thin).
   Adopt **Claude Code's on-disk conventions** wherever we have an equivalent concept.

## 2. Non-goals (v1)

- No multi-agent pipeline builder UI (LogRocket-style Dev→QE→Ops); P2 subagents are the
  primitive it would later build on.
- No container sandbox requirement — v1 executes on the host behind the permission
  engine and path jail (Option-A local-first posture); container runner is P4 opt-in.
- No ACP server, no hooks, no compaction rewrite, no memory-hierarchy loading in v1
  (P2/P3).
- No hosted/multi-tenant semantics beyond what `tenancy.py` already provides.
- No change to non-workspace chats: without an attached folder, behavior is exactly
  today's.

## 3. Concept & UX

A chat (or Cowork task) can be **attached to a Workspace** — a local folder chosen via
the Tauri folder dialog (recents list kept). Attached, the composer shows a workspace
bar (folder name, permission-mode selector, checkpoint/rewind menu) and the agent
gains the workspace tool suite. The chat renders a live **tool timeline** (structured
tool cards with input summary, duration, status), **file diffs** for edits, and a
**plan card** driven by the model's plan tool.

Feature name: **Harness**. UI copy: "Work in a folder".

## 4. Architecture

New package `backend/ocd_core/harness/`; each module has one purpose and integrates
into the existing spine — `run_turn` is extended, not rewritten.

```
ocd_core/harness/
  workspace_fs.py    path jail + read_file/edit_file/write_file/glob/grep impls
  rules.py           permission modes + allow/deny/ask rule engine
  checkpoints.py     pre-edit snapshots, per-prompt checkpoints, restore
  plan_tool.py       model-driven task plan (create/update items, statuses)
  env_context.py     env section for the system prompt (platform, git, file map)
  hooks.py           (P2) PreToolUse/PostToolUse/... — Claude JSON contract
  subagents.py       (P2) defined agents + Agent tool, generalizing run_turn's flag
```

Integration points:

- **Tool registration:** the five fs tools + `task_plan` join the existing tool-spec
  assembly and the `_run_one_tool` dispatch in `agent.py`, gated by a new
  `workspace_root: str | None` parameter on `run_turn` (absent → tools absent,
  today's behavior).
- **Permission flow:** the existing sensitive-tool gate (agent.py, next to the
  Track-2 domain gate) consults `rules.py` first; only an `ask` outcome reaches
  `permissions.PermissionRegistry.wait()` and the existing `approval_required`
  SSE + `ApprovalPrompt.tsx` flow. `resolve()` semantics unchanged.
- **Routes:** `routes/agent.py` stays the single agent SSE surface; `AgentTurnRequest`
  gains `workspace_id`. New thin routes: workspace CRUD/pick-recents, checkpoint
  list/restore. Cowork's `Task` gains `workspace_id` the same way.
- **Persistence:** workspace registry (id → root path, rules, protected paths,
  recents) + checkpoints live under the app data dir (`workspace_store.py` pattern);
  routes carry `workspace_id`, and the route layer resolves it to `workspace_root`
  before calling `run_turn`. Nothing agent-generated is written inside the user's
  folder except what the model explicitly edits.

## 5. Workspace & path jail

One jail function used by every fs tool (and by `bash`'s cwd validation):

- Normalize via `Path.resolve()` (realpath); the result must be equal to or under the
  workspace root. Windows specifics are first-class: case-insensitive comparison,
  junction and symlink resolution, UNC and `\\?\` long paths, 8.3 short names
  resolved before comparison.
- Escapes fail closed with a distinct error the model can read (`path_outside_workspace`).
- **Protected paths** (write-gated even in `acceptEdits`): the app's own config/data
  dirs, `.git/` internals (reads allowed), and a default secret-shaped set
  (`.env*`, `*.pem`, `id_*`) — configurable per workspace.
- The jail is a pure function (`resolve_in_workspace(root, user_path) -> Path | JailError`)
  so it is exhaustively unit-testable.

## 6. Tool suite (P1)

Claude Code's proven semantics, adapted to our snake_case tool naming:

| Tool | Contract (the drift-guards are the point) |
|---|---|
| `read_file` | `cat -n`-style line numbers; `offset`/`limit`; bounded output with head/tail truncation via `context.truncate_tool_result` |
| `edit_file` | `old_string`/`new_string`; **fails unless `old_string` matches exactly once** (or `replace_all: true`); file must have been read this turn before editing |
| `write_file` | create/overwrite; **overwrite requires a prior read this turn**; snapshots via checkpoints before write |
| `glob` | pattern match under workspace, mtime-sorted, capped count |
| `grep` | regex content search (line/files/count modes), bounded output, capped matches |
| `bash` | existing tool, now `cwd=workspace_root`, timeout defaulted, output capped; stays `SENSITIVE_TOOLS`-classified |

Existing tools (`web_search`, `web_fetch`, `run_sql`, MCP, artifacts, `memory`, …)
are unchanged and compose freely with the suite.

## 7. Permission system

**Modes** (superset of today's three; unknown modes still fail closed to `strict`):

| Mode | Behavior |
|---|---|
| `default` | rules first; sensitive/unmatched → prompt (today's `ask`) |
| `acceptEdits` | `default` + auto-approve jailed file edits and safe-listed bash (initial safe list mirrors Claude Code's: `mkdir`, `touch`, `mv`, `cp`, `rm`, `rmdir`, `sed` scoped to the jail — defined in `rules.py`, user-extensible via allow rules) |
| `plan` | read-only tools only; any mutation prompts |
| `strict` | prompt for every tool (unchanged) |
| `bypass` | today's `auto`: no prompts, fully audited |

Legacy mode names remain accepted as aliases (`auto` → `bypass`, `ask` → `default`)
so existing configs and API callers keep working; the alias mapping lives in
`rules.py` beside the mode definitions.

**Rules:** `allow` / `deny` / `ask` arrays of `tool(matcher)` patterns —
`bash(git *)`, `edit_file(src/**)`, bare `web_fetch` for all invocations. Precedence:
**deny > ask > allow > mode default**. Evaluation lives in `rules.py` as pure
functions over (tool, args, mode, rule-set).

**Storage & compatibility:** per-workspace rules in the app's workspace store,
editable in Settings; additionally, a workspace's **`.claude/settings.json`
`permissions` block is read** (mapped tool names, best-effort, log-on-parse-error) so
Claude Code users' existing rules carry over. Ours win on conflict.

**UI:** `ApprovalPrompt.tsx` gains an "Always allow …" option that writes a scoped
allow rule (workspace-level), mirroring Claude Code's prompt affordance.

## 8. Checkpoints & rewind

- Before a turn's **first** mutation of each file: snapshot into a content-addressed
  per-workspace store (app data dir), keyed `(checkpoint_id, relpath, blob_hash)`.
- Every user prompt in a workspace chat opens a checkpoint (id = turn id).
- Retention: last 100 checkpoints per workspace (Claude Code's number), pruned FIFO.
- Endpoints: list checkpoints for a conversation; restore `{files | conversation | both}`
  to a checkpoint. Conversation restore reuses the existing conversation-store
  truncation; file restore writes snapshots back through the jail.
- SSE `checkpoint` events let the UI render rewind anchors on messages.
- **Documented limitation** (same as Claude Code): mutations made by `bash` (`rm`,
  `mv`, `sed`, …) are not snapshotted; the git-integration upgrade is P4.

## 9. Plan tool

`task_plan` tool with `set`/`update` operations over items
`{id, subject, status: pending|in_progress|completed}` — one active plan per turn,
persisted onto the Cowork/conversation event stream as `plan_update` events, rendered
as a live plan card (chat) and in `CoworkPanel` (background tasks). The system prompt
instructs plan usage for multi-step work — same behavioral contract as Claude Code's
task tracking, which is what keeps long tasks anchored to the goal.

## 10. Environment context

`env_context.py` assembles a bounded, deterministic env section appended to the
system prompt for workspace turns: platform + OS, workspace root, git state (branch,
dirty-file count, last 5 commit subjects — via `git_sync.py` helpers, never failing
the turn if git is absent), and a depth-2 file map capped at 200 entries. Modeled on
Claude Code's env block; content ordered stably for prompt-cache friendliness.

## 11. Streaming events & desktop UI

Additions to the existing SSE vocabulary (ACP-shaped names; no envelope change):

- `tool_call` (start/end, name, input summary, duration, status, tc_id)
- `file_diff` (relpath, unified diff, tc_id) — emitted by `edit_file`/`write_file`
- `plan_update` (full plan snapshot)
- `checkpoint` (id, turn id)

Existing `approval_required`, `delta`, file/completion events unchanged — Cowork's
`_derive_files`/`_derive_progress` keep working, upgraded to prefer the structured
events when present.

Desktop: workspace picker + recents (Tauri dialog), workspace bar with mode selector,
tool timeline cards in `Message.tsx`, diff rendering via `CodePanel.tsx`, rewind menu,
plan card. New settings page: Workspaces (roots, rules, protected paths).

## 12. Safety posture & audit

- Host execution behind jail + rules + HITL is the v1 boundary (consistent with
  Track-2's "local, deterministic, on by default" stance); container sandbox is P4.
- Every permission decision (`rule_allow`/`rule_deny`/`prompted`/`auto`) is audited
  through `observability.audit` alongside the existing egress audit trail.
- Prompt-injection posture: fs tools cannot leave the jail; egress controls (domain
  approval, redaction) already cover the exfil path; `bash` remains prompted-by-default
  in `default`/`acceptEdits` unless safe-listed; protected paths keep secrets
  write-gated.
- Fail-closed inheritance: unknown modes → `strict`; jail errors → tool error, never
  fallback to unjailed IO; rules parse errors → rule ignored + audited, never crash.

## 13. Testing

- **Unit:** jail adversarial suite (junctions, symlinks, UNC, 8.3 names, `..`
  traversal, case tricks, prefix-sibling roots e.g. `C:\ws` vs `C:\ws2`); rules
  precedence matrix; checkpoint round-trip incl. binary + CRLF files; plan-tool
  transitions; env-context determinism.
- **Loop-level:** fake-LLM turns per the `test_agent_hitl.py` pattern — edit flow
  (read→edit→diff event), `acceptEdits` auto-approval, `plan` mode blocking a write,
  "always allow" rule persistence, checkpoint restore mid-conversation.
- **Desktop:** vitest for workspace bar, tool timeline, diff card, rewind menu.
- **Process:** per repo convention (Track-2), an adversarial verify pass on the jail
  and the rules engine before merge; TDD (red → green) per module.

## 14. Roadmap — tracked phases to Claude parity

| Phase | Contents |
|---|---|
| **P1 — SHIPPED** (branch `feat/harness`, 2026-07-21) | workspace + jail, fs tool suite, modes + rules, checkpoints/rewind, plan tool, env context, SSE/UI |
| **P2** | hooks (Claude JSON stdin/stdout contract: PreToolUse/PostToolUse/UserPromptSubmit/Stop/SessionStart, matchers, allow/deny/additionalContext); generalized subagents (`.claude/agents/*.md`-compatible defs, Agent tool, fresh context, tool scoping); skills/commands upgraded to full Claude formats (`$ARGUMENTS`, `allowed-tools`) |
| **P3** | compaction upgrade (tool-aware: preserves call/result pairs; optional LLM summarization above today's extractive `context.py`); memory hierarchy (workspace `CLAUDE.md`/`AGENTS.md` + user-level, injected cache-friendly); background bash + job-queue integration |
| **P4** | opt-in container sandbox runner (`backend/sandbox/`); ACP server exposure; checkpoint-git integration; auto permission mode (classifier-reviewed) if/where model support allows |

Each phase gets its own spec → plan → implementation cycle; this document is the
umbrella reference.

### P1 as-built — deltas from this spec (recorded 2026-07-21)

The implementation (plan: `docs/superpowers/plans/2026-07-20-harness-phase1.md`) matched
the design; two-stage review during execution hardened these points, which supersede the
spec text where they differ:

- **Permission modes (§7) — `bypass` is safety-scoped, deviating deliberately from
  "bypass = today's auto".** The mode/rule gate governs only the harness tools (file
  suite + `task_plan` + `bash`); it is NOT applied to the pre-existing sensitive
  built-ins (`code_execution`, `authenticate`, memory mutations), which keep their
  existing HITL gate. So `bypass` auto-runs the *coding* tools (minus the
  catastrophic-bash breaker) but a sensitive built-in still prompts — only the legacy
  literal `auto` turns the gate fully off. This closes a review-found hole where an
  unscoped gate let `bypass` skip the HITL prompt for `code_execution`.
- **Catastrophic-bash circuit breaker** (`rules.is_catastrophic_bash`): a mode-independent
  hard `deny` for `rm -rf /`/`~`, fork bombs, `mkfs`, disk-device writes — overrides
  `allow` rules and `bypass` alike (best-effort defense-in-depth, not a sandbox). Lands
  because `bash` args are not jailed (only its cwd is).
- **Protected paths (§5) are enforced as generated `ask`-rules** (`edit_file`/`write_file`
  on each glob, bare + `*/`-nested), so `.env`/`*.pem`/`id_*` prompt even in `acceptEdits`.
- **Routes live under `/harness/workspaces`** (tenancy already owns `/workspaces`).
- **Checkpoints are workspace-bound**: the manifest stamps its owning workspace root and
  restore/list verify it (`owned_by`), so one workspace can never restore into another
  (cross-workspace overwrite was a review-caught Critical).
- **Rewind is file-restore only in v1**; conversation restore is deferred (desktop-side).
- **`bash` cwd — SHIPPED in the P1.5 fast-follow** (spec/plan `2026-07-21-workspace-cwd-bash`,
  branch `feat/harness-bash`). P1 left `bash` on the read-only `SANDBOX_ROOT` sandbox; the
  fast-follow gives `run_bash` a jailed workspace cwd + a curated runner allowlist
  (`WORKSPACE_BASH_ALLOW`: pytest/npm/cargo/go/make/… + `python`/`node` on the repo's own
  script files, inline `-c`/`-e`/REPL blocked), a `--flag=<path>` arg-jail, and secret-env
  stripping — all behind the existing mode gate + catastrophic breaker. Runners still
  prompt in `default`/`acceptEdits` unless rule-allowed. Adversarially verified (attached-eval,
  interpreter-front, arg-jail, DoS, env-leak). It is host execution, not a sandbox — the
  P4 container runner remains the answer for untrusted repos.
- **Deferred to a fast-follow (not P1 blockers):** checkpoint
  FIFO pruning (`MAX_CHECKPOINTS` reserved); `glob`/`grep`/env-map walk-then-filter perf on
  large `.git`/`node_modules`; the `env_context` depth-cap has no "truncated" marker.
- **Unknown/stale `workspace_id`** degrades to a normal (folderless) chat AND emits a
  `workspace_detached` SSE event + `workspace_attach_failed` audit, so the model never
  silently over-claims folder access (the CSV-hallucination incident's failure shape).

## 15. Risks & mitigations

- **Path jail on Windows is subtle** → pure-function jail + adversarial test suite +
  verify pass; deny-by-default on resolution errors.
- **Cross-provider tool-schema drift** (Gemini thought signatures, OpenAI-compat
  quirks) → suite rides the existing provider layer which already handles streamed
  tool calls (PR #93); loop tests run against recorded fixtures per provider.
- **Permission UX fatigue** → `acceptEdits` + "always allow" rules + safe-listed bash
  defaults; audit keeps bypass honest.
- **Scope creep toward parity-everything** → phases are hard boundaries; P1 ships
  user-visible value alone (a working folder coding agent).

## 16. References

- Claude Code docs: how-it-works, tools-reference, permissions/permission-modes,
  hooks, sub-agents, skills, MCP, memory, checkpointing, Agent SDK overview
  (code.claude.com/docs).
- shareAI-lab/learn-claude-code — 20-chapter Python harness curriculum (loop →
  tools → permissions → hooks → planning → subagents → skills → compaction → memory
  → background → MCP).
- Agent Client Protocol (agentclientprotocol.com) — event-shape reference for §11.
- Uploaded studies: LogRocket "Build an agent harness with Claude Code";
  dailydoseofds "Rebuilding Claude Code's harness" (CrewAI); Reddit "What I learned
  about Claude Code by rebuilding its harness" (gate/evidence hooks — P2 hook
  contract makes such systems pluggable).
- In-repo: `docs/track2-local-agent-safety-plan.md`, `docs/architecture-audit.md`.
