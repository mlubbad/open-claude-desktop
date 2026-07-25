# Harness P2a — Hooks — Design

> **Status:** Approved by user 2026-07-22. **Line:** `origin/main` @ `f794444` (P1 #102 + P1.5 bash #103 merged), branch `feat/harness-hooks`.
> **Scope:** deterministic, user-owned interception points around the agent loop. One of three P2 sub-projects (see §11).

## 1. Context & goal

P1 gave the harness a **policy** layer (permission modes + allow/deny/ask rules + the
catastrophic-bash breaker) and a **HITL** layer (the approval prompt). Neither is
programmable: a user can't say "run my checker before every `bash`", "log every tool call
to my telemetry DB", or "inject this context at the start of every turn".

**Hooks** are that programmable layer — shell commands the app runs at fixed lifecycle
events, receiving the event as JSON on stdin and returning a decision on stdout. They run
**outside the model's context**: they cost no tokens, and the model cannot argue with them.
This is what makes external gate/evidence systems and telemetry harnesses *pluggable*
rather than hard-coded — the two patterns from the studied sources (a `PreToolUse` gate +
`PostToolUse` evidence capture; a stage/tool telemetry recorder) become things a **user**
builds on top of this feature, not things we ship.

### What exists to build on (recon 2026-07-22, `origin/main`)
| Seam | Where |
|---|---|
| Rules gate (modes + allow/deny/ask + breaker), scoped to harness tools | `harness/rules.py` `gate()`, called in `agent.py` (workspace-tool gate block) |
| HITL approval (suspends the turn, fails closed on timeout) | `permissions.PermissionRegistry` + `approval_required` SSE + `ApprovalPrompt.tsx` |
| Tool dispatch + outcome events | `agent._run_one_tool`, `_completion_events` |
| Audit trail | `observability.audit` |
| Settings (app-owned, user-editable) | `config.DEFAULT_SETTINGS` + `settings.py` |
| **Hooks** | **nothing — greenfield** (grep for `hook` in `agent.py`: zero matches) |

### Decisions (user-approved 2026-07-22)
1. **Trust boundary — app settings ONLY.** Hook definitions are read from the app's own
   settings (user-owned). They are **never** auto-loaded from a workspace's
   `.claude/settings.json`. A cloned repo must not be able to ship a command that executes
   on the host merely because the folder was attached. (P1 *does* read a workspace's
   `.claude/settings.json` **permission rules** — those only ever *restrict*; a hook
   *executes*. Different risk class, different rule.)
2. **`type: "command"` hooks only.** Shell command + JSON stdin/stdout, Claude's contract.
   `http`, `prompt`, and `agent` hook types are deferred (§10).
3. **Fail-closed on `PreToolUse`**, fail-open on observational events (§6).
4. **A hook may only tighten, never loosen** an existing decision (§6).

## 2. Non-goals (v1)
- No workspace-supplied hooks (decision 1) and no per-workspace trust flow.
- No `http`/`prompt`/`agent` hook types.
- No desktop settings UI for editing hooks (settings JSON + the audit trail are the v1
  surface); a UI is a follow-up.
- No `SubagentStart`/`SubagentStop`/`PreCompact`/`Notification` events (P2b/P3 territory).
- No change to the P1 rules gate, the breaker, or the HITL flow — hooks *compose with*
  them, they do not replace them.
- Hooks do not run for non-workspace chats' existing sensitive-tool gating semantics in
  any way that changes today's behavior when no hooks are configured (zero configured
  hooks ⇒ byte-for-byte today's behavior).

## 3. Events (v1 — five)

| Event | Fires | May return |
|---|---|---|
| `SessionStart` | once, as a turn begins | `additionalContext` |
| `UserPromptSubmit` | after the goal is known, before it reaches the model | `additionalContext`; **block** the turn |
| `PreToolUse` | before a tool executes — **after** the P1 rules gate, **before** the HITL prompt | `allow` \| `deny` \| `ask` (tightening only) |
| `PostToolUse` | after a tool returns its outcome | `additionalContext` (observational) |
| `Stop` | the turn is about to finish | `additionalContext` (observational) |

**Ordering at a tool call** (as built — corrected 2026-07-22 after implementation):
```
PreToolUse hook  →  [deny? stop | ask-with-no-channel? stop]
                 →  rules.gate()  →  [deny? stop | allow (and no hook "ask")? run]
                 →  HITL prompt (if "ask" from either)  →  execute  →  PostToolUse hook
```
> The hook runs **before** `rules.gate`, not after as originally drafted: the gate's own
> `allow` branch `continue`s straight to execution, so a hook placed after it would never
> be consulted for a workspace tool in a permissive mode. Security is unaffected — the
> gate's `deny` branch and the catastrophic-bash breaker never consult the hook's decision,
> so a hook still cannot loosen either (verified adversarially). The gate's `allow` branch
> **does** check `_hook_forces_ask`, so a hook can still tighten.

**Explicitly, per gate outcome** (an implementer will hit all three):

| `rules.gate` says | Effect of the hook's answer |
|---|---|
| `deny` | Hook already ran, but the gate's deny is unconditional — a hook can never resurrect it |
| `ask` | `deny` → block; `allow` → skip the prompt; `ask`/none → prompt as usual |
| `allow` | `deny` → block; `ask` → **force** the prompt (tightening); `allow`/none → run |

Non-workspace turns have no `rules.gate` (it is workspace-scoped), so `PreToolUse` tightens
the existing `permissions.requires_approval` check the same way.

**Unattended runs (no HITL channel).** When `gate_on` is false — `permission_mode="auto"`,
i.e. Cowork/scheduler — there is no one to prompt. A hook's `deny` still blocks
(unconditional). A hook's **`ask` also blocks**: "ask with nobody to ask" fails closed
rather than silently proceeding, so the tighten signal cannot invert into "allow" exactly
when no human is watching (§6.7).

**A hook's `allow` skips the HITL prompt — including for sensitive built-ins.** That is the
intended trust delegation (only the app operator can author a hook at all), and it is the
same power `bypass` mode already grants. It deserves the same caution in SECURITY.md: a
broad-matcher `allow` hook effectively disables approval prompts.

## 4. Contract (Claude-compatible)

**Input** (JSON on stdin):
```json
{"event":"PreToolUse","session_id":"…","turn_id":"…","cwd":"<workspace root or ''>",
 "tool_name":"bash","tool_input":{"command":"pytest -q"},"tool_response":null}
```
`tool_name`/`tool_input` are present for `PreToolUse`/`PostToolUse`; `tool_response` only
for `PostToolUse`. `prompt` is present for `UserPromptSubmit`.

**Output** — either JSON on stdout (exit 0):
```json
{"permissionDecision":"deny","reason":"blocked by policy","additionalContext":"…","suppressOutput":false}
```
…or bare exit codes: **0** = proceed (stdout ignored if not JSON), **2** = block/deny
(stderr becomes the reason), **any other** = error (see §6).

**Config** (app settings, `hooks` key):
```json
{"hooks": {
  "PreToolUse": [{"matcher": "bash|edit_file", "command": "python C:/gate/check.py", "timeout": 30}],
  "PostToolUse": [{"matcher": "*", "command": "python C:/gate/record.py"}]
}}
```
`matcher` is a regex on the tool name (`*` / omitted = all); for non-tool events the
matcher is ignored. Multiple hooks per event run in order; **the strictest decision wins**
(`deny` > `ask` > `allow`), and all `additionalContext` strings are concatenated.

## 5. Architecture

New module `backend/ocd_core/harness/hooks.py` — the single owner of matching, execution,
timeout, and decision parsing. Call sites just await it.

```
hooks.py
  HookDecision            dataclass: decision ("allow"|"deny"|"ask"|None), reason, context
  load_hooks(event)       -> list[dict]      # from settings; [] when unconfigured
  matches(hook, tool)     -> bool            # regex on tool name
  async run(event, payload) -> HookDecision  # execute all matching hooks, merge results
```

**Call sites in `agent.py`** (five, each a 2–4 line await):
- `SessionStart` — at turn start; its `additionalContext` joins `extra_sections`.
- `UserPromptSubmit` — before the user message is appended; `deny` ends the turn with the
  reason as the answer; `additionalContext` is appended to the goal.
- `PreToolUse` — immediately after the rules-gate block, before `permissions.requires_approval`.
- `PostToolUse` — in the outcome loop, after `_completion_events`.
- `Stop` — before the final answer is finalized.

**Execution details:** `shell=False` with the command tokenized via `shlex.split`; JSON on
stdin; default `timeout` 30s (per-hook override, capped at 120s); stdout/stderr capped;
the child env is the sanitized env already used by workspace bash (`_sanitized_child_env`),
so hooks can't read `OCD_API_TOKEN`/provider keys; `cwd` = the workspace root when attached,
else the app data dir.

**Zero-config short-circuit:** `load_hooks` returns `[]` when the settings key is absent,
and `run()` returns a no-op decision without spawning anything — so an app with no hooks
configured behaves byte-for-byte as today (and pays no subprocess cost).

## 6. Safety model (the crux)

1. **Trust:** hooks come only from app settings (decision 1). The spec, README, and
   SECURITY.md must state plainly that a workspace cannot contribute a hook.
2. **Fail-closed where it matters:** for `PreToolUse`, a hook that times out, crashes,
   exits non-zero-non-2, or emits unparseable JSON ⇒ the tool call is **denied**, with the
   failure surfaced to the model as the tool error and written to the audit trail. A broken
   gate must never silently become an open gate.
3. **Fail-open where it can't hurt:** `PostToolUse`, `Stop`, and `SessionStart` failures are
   logged + audited and otherwise ignored — an observational hook can't make an unsafe
   thing happen, and shouldn't be able to brick the app.
4. **Tighten-only:** hooks run *after* `rules.gate`. If the gate (or the catastrophic-bash
   breaker) already returned `deny`, the tool is already blocked and no hook runs for it —
   a hook's `allow` can never resurrect it. A hook's `allow` means only "skip the HITL
   prompt that would otherwise show"; `ask` forces the prompt even where the mode would
   have auto-approved; `deny` blocks.
5. **Bounded:** timeout (default 30s, max 120s), output caps, `shell=False`, sanitized env,
   and secret-scrubbed output before anything reaches the model or the log.
6. **Audited:** every hook run records `{event, hook_command, tool, decision, duration_ms,
   ok}` via `observability.audit`.
7. **Unattended runs:** hooks fire for Cowork/scheduler turns too (they are policy, and
   policy should not evaporate when the user isn't watching). Because they are app-owned,
   this adds no new injection surface.

## 7. Failure & error handling summary

| Situation | `PreToolUse` | Observational events |
|---|---|---|
| exit 0 + valid JSON | apply decision | apply `additionalContext` |
| exit 0 + non-JSON stdout | proceed (no decision) | ignore |
| exit 2 | **deny** (stderr = reason) | log only |
| other non-zero / crash / not found | **deny** + audit | log + audit, continue |
| timeout | **deny** + audit | kill, log + audit, continue |
| malformed JSON | **deny** + audit | ignore + audit |

## 8. Testing
- **Unit (`hooks.py`):** matcher semantics (regex, `*`, omitted); each decision path; the
  strictest-wins merge across multiple hooks; exit-code mapping (0/2/other); timeout→deny
  for `PreToolUse`; malformed-JSON→deny; fail-open for `PostToolUse`/`Stop`/`SessionStart`;
  `load_hooks` returns `[]` and `run()` spawns nothing when unconfigured; sanitized env
  (a hook cannot read `OCD_API_TOKEN`).
- **Loop-level (fake-LLM, the `test_agent_hitl.py` pattern):** a `PreToolUse` `deny` blocks
  the tool and the model receives the reason; a `PreToolUse` `ask` forces the approval
  prompt in a mode that would otherwise auto-approve; `UserPromptSubmit` `additionalContext`
  reaches the model; `UserPromptSubmit` block ends the turn cleanly; `PostToolUse` observes
  without altering the outcome; **a hook returning `allow` does NOT override a `rules.gate`
  deny**; with no hooks configured the turn is unchanged (regression).
- **Regression:** `test_agent_hitl.py`, `test_permissions.py`, `test_harness_rules.py`,
  `test_agent_workspace.py`, `test_bash_jail.py` all stay green.
- **Process:** per repo convention, an adversarial verify pass on the hook runner before
  merge (can a hook escape the sanitized env? can a malformed decision open a gate? can a
  hook command be injected from a workspace file?). TDD (red→green) per module.

## 9. File structure
- **Create** `backend/ocd_core/harness/hooks.py` (runner + contract).
- **Modify** `backend/ocd_core/agent.py` — five call sites.
- **Modify** `backend/ocd_core/config.py` — `DEFAULT_SETTINGS["hooks"] = {}` + timeout consts.
- **Tests** `backend/tests/test_harness_hooks.py` (unit) + extend `test_agent_workspace.py`
  (loop-level).
- **Docs** README (a Harness → Hooks subsection), SECURITY.md (hooks are app-settings-only,
  fail-closed on PreToolUse), and the P1 spec's roadmap row for P2a.

## 9b. Known limitations (adversarially verified 2026-07-22, accepted for v1)

13 attack classes were probed against the built feature; 10 held clean and 3 escapes were
found and fixed (hook `ask` evaporating in unattended runs; a detached grandchild surviving
a timed-out hook — now killed tree-wide; `DATABASE_URL`-style credential env vars passing
the secret filter — pattern widened, which also hardens workspace bash). Two findings were
accepted rather than fixed, and are documented for the operator:

- **`PreToolUse` latency scales with hook count.** Hooks for one event run sequentially, so
  aggregate worst case is `N × timeout`. Each hook is individually capped (default 30s, max
  120s) and every `PreToolUse` hook blocks each tool call — keep them few and fast.
- **A pathological matcher regex can hang the loop.** `matches()` has no regex timeout, so a
  catastrophic-backtracking pattern (e.g. `^([a-z_]+)+$`) written into app settings will
  stall. Tool names come from a fixed internal vocabulary (an injected name is rejected
  before the hook loop), so this is self-inflicted only — but it is the one unbounded path.

## 10. Deferred (explicitly not v1)
`http`/`prompt`/`agent` hook types; `SubagentStart`/`SubagentStop`/`PreCompact`/`Notification`
events; a per-workspace trust flow for workspace-supplied hooks; a desktop settings UI for
hooks; hook output streaming into the chat transcript.

## 11. Relationship to the rest of P2
- **P2a (this spec)** — hooks. Independent; ships first.
- **P2b — generalized subagents:** `.claude/agents/*.md`-compatible named definitions with
  per-agent `tools`/`model`/`permissionMode`, replacing today's single anonymous
  `spawn_subagent`. **Open safety issue to design there:** subagents currently run
  `permission_mode="auto"`, so granting them workspace file tools would mean *ungated
  writes*; P2b must resolve that deliberately. Benefits from hooks existing (per-agent
  `SubagentStart`/`Stop`).
- **P2c — skills/commands Claude-format upgrade:** `skills.py` already parses
  `name`/`description`/`auto`/`triggers`/`file_triggers`/`references` but not
  `allowed-tools`, `$ARGUMENTS`, or `argument-hint`. Small, independent, any time.

## 12. Risks & mitigations
- **A broken hook blocks all tools** (the cost of fail-closed) → the denial reason names the
  hook command and the failure mode, so it's self-diagnosing; hooks are per-event and
  per-matcher, so the blast radius is scoped; disabling is a settings edit.
- **Hook latency on every tool call** → default 30s cap, and zero-config costs nothing;
  document that `PreToolUse` hooks should be fast.
- **Command injection via tool input** → the hook command comes from settings and is
  tokenized (`shell=False`); tool input is passed as **stdin JSON**, never interpolated
  into the command line.
- **Windows** → commands are tokenized with `shlex.split(posix=False)`-appropriate handling
  and executed without a shell; tests cover a `python <script>` hook (portable), not
  `echo`/shell builtins (the documented Windows-baseline trap).

## 13. References
- Claude Code docs: hooks guide + hooks reference (events, JSON contract, exit codes,
  matchers), Agent SDK hooks.
- In-repo: `harness/rules.py` (the gate hooks compose with), `permissions.py` (HITL),
  `integrations._sanitized_child_env` (the env hooks inherit), `observability.audit`.
- Studied sources this unblocks (as *user-built*, not shipped): the tiered gate +
  evidence-capture pattern (`PreToolUse`/`PostToolUse`), and stage/tool telemetry recording.
