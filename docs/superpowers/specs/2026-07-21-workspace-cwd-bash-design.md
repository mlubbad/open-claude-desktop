# Workspace-cwd bash — Design (Harness P1.5 fast-follow)

> **Status:** Approved by user 2026-07-21. **Line:** `feat/harness` (Harness P1, PR #102) → new fast-follow branch.
> **Scope:** let a workspace-attached agent run build/test **runners** in the attached folder, not just the read-only `SANDBOX_ROOT`. One backend change + tests; no desktop change.

## 1. Context & goal

Harness P1 (PR #102) gave the agent jailed file tools (`read_file`/`edit_file`/`write_file`/`glob`/`grep`) that operate on the attached workspace, but `bash` was left as the pre-existing tool: it runs in `SANDBOX_ROOT` (not the workspace) against a **read-only** allowlist (`integrations._BASH_ALLOW` = `ls, cat, echo, pwd, grep, wc, head, tail, type, dir, date, whoami, sort, uniq, cut`), single-command only, no shell metacharacters. So the agent can **edit** files in the folder but cannot **run its tests/build** there — the half of the coding loop the harness articles centre on (edit → run → verify).

This closes that gap: in a workspace turn, `bash` runs in **`cwd=workspace_root`** against a **broader runner allowlist**, still behind the existing permission gate. It stays **host execution behind the mode gate** — consistent with P1's local-first (Option-A) posture; the container sandbox is a separate later step (P4), not required here.

### Decisions (user-approved 2026-07-21)
1. **Command policy:** a **curated runner allowlist** applied only in workspace turns (not "any command"; not per-workspace-configured). Non-workspace turns keep the read-only `_BASH_ALLOW` unchanged.
2. **Interpreters:** `python`/`node`/etc. are in the default list so the agent can run the repo's own scripts (`python manage.py test`, `node build.js`), **but inline-eval flags are rejected** (`-c`, `-e`, `--eval`, and a lone stdin `-`) so the model can't run code it wrote inline.
3. **Shell features:** keep today's **single-command** restriction (the `&& | ; > < .. $() ${} backtick newline` ban stays) — the model runs commands one at a time; far smaller injection surface. Chaining/pipes/redirects are explicitly out of scope.

## 2. Non-goals
- No shell chaining / pipes / redirects / command substitution (single command only, as today).
- No background / long-running processes (the 120s-timed, capture-then-return model stays).
- No container sandbox (that's P4; this is host execution behind the gate).
- No per-workspace user-configurable command list (rejected in favour of the curated default; a user can still broaden/narrow via `allow`/`deny` **rules**, which already exist).
- No desktop change — the tool timeline already renders `bash`.
- Non-workspace bash behaviour is byte-for-byte unchanged.

## 3. Architecture — two layers, already separated

**A. Execution layer — `integrations.run_bash`.** Extend the signature (keyword-only, all defaulting to today's behaviour):

```python
def run_bash(command, restart=False, *, root=None, allow=None, timeout=None) -> str
```

- `root` (workspace turn) → the subprocess `cwd`; the arg-jail re-roots to it. `None` → `SANDBOX_ROOT` (today).
- `allow` → the allowlist set to check `parts[0]` against. `None` → `_BASH_ALLOW` (today's read-only set).
- `timeout` → seconds; `None` → today's `30`.
- **Everything else is unchanged and still applies in workspace mode:** the metacharacter/`..` ban (single command), `shlex.split`, the `parts[0] in allow` check, secret scrubbing, the 16 000-char output cap, `shell=False`.

**B. Decision layer — `rules.gate` (unchanged).** The runner commands are **not** added to `SAFE_BASH`, so in a workspace turn they resolve to **`ask`** in `default`/`acceptEdits` (prompt), `allow` in `bypass`, and the **catastrophic-bash breaker still hard-denies** `rm -rf /`-class commands in every mode. A user who wants their test command to auto-run adds an `allow` rule (`bash(npm test)`, `bash(pytest*)`) — the tight edit→test loop, opt-in per workspace. No change to `rules.py` is required for the default behaviour; the breaker and gate already cover `bash`.

**Agent wiring (`agent.py`, `_run_one_tool` bash branch, ~`:1044`).** When the turn's `ws` context is present, pass the workspace params:
```python
result = await asyncio.to_thread(
    integrations.run_bash, args.get("command", ""), bool(args.get("restart")),
    root=ws["root"], allow=integrations.WORKSPACE_BASH_ALLOW,
    timeout=config.WORKSPACE_BASH_TIMEOUT_SEC)
```
`ws` is already threaded into `_run_one_tool` (P1). Non-workspace turns call `run_bash` exactly as today.

## 4. The workspace allowlist + interpreter guard (`integrations.py`)

```python
# Read-only base (today) PLUS build/test runners — used ONLY when run_bash gets an explicit `allow`.
WORKSPACE_BASH_ALLOW = _BASH_ALLOW | {
    "pytest", "python", "python3", "node", "npm", "pnpm", "yarn",
    "go", "cargo", "make", "tsc", "ruff", "mypy", "eslint", "jest", "vitest",
    "git", "which", "tox", "poetry", "uv",
}
# Deliberately EXCLUDED from the default (add per-workspace via an `allow` rule if wanted):
#   find  — `-delete`/`-exec` run/remove arbitrary things (CLAUDE.md excludes it; use `glob` instead)
#   npx   — runs an arbitrary npm package (download-and-execute)
#   env   — can front an interpreter to dodge the inline-eval guard (`env python -c …`)
# Interpreters whose inline-eval flags let the MODEL run code it wrote → block those flags.
_INTERPRETERS = {"python", "python3", "node", "deno", "ruby", "perl", "php"}
_INLINE_EVAL_FLAGS = {"-c", "-e", "--eval", "-"}
```

`run_bash`, after the existing `parts[0] in allow` check and **only when a non-default `allow` is in force** (workspace mode), adds:
```python
if parts[0] in _INTERPRETERS and any(a in _INLINE_EVAL_FLAGS for a in parts[1:]):
    return ("Rejected: inline code (-c/-e/--eval/stdin) is not allowed. Run a file "
            "in the workspace instead (e.g. `python script.py`).")
```
Rationale: `pytest`/`npm`/`make` run the *project's own* scripts (semi-trusted — it's the user's repo); the inline-eval block closes the distinct hole where the model supplies arbitrary code inline. `git` is included for `git status`/`diff`/`log`; the mode gate + breaker govern any mutating git.

**Arg-jail re-rooting.** `_bash_arg_escapes_jail` currently hardcodes `SANDBOX_ROOT`. Parameterise it — `_bash_arg_escapes_jail(tok, root)` — and pass the active root from `run_bash`. Behaviour is identical (reject absolute/home/UNC/drive paths and relative tokens that resolve outside `root`); it just jails to the workspace in workspace mode. Flags (leading `-`) stay exempt, so `npm test -- --coverage` and `pytest -k foo` work; `make test` / `npm run build` pass (targets resolve inside the root or don't exist, which is allowed).

## 5. Timeout, environment, PATH
- `WORKSPACE_BASH_TIMEOUT = 120` (config-overridable, `OCD_WORKSPACE_BASH_TIMEOUT_SEC`) — builds/tests exceed 30s. Output still capped at 16 000 chars and secret-scrubbed.
- The subprocess inherits the backend's environment (so `PATH` finds the runners). **Packaged-app caveat:** the frozen desktop ships a pinned Node as `ocd-node` (`OCD_NODE`) that may not be on `PATH`; `npm`/`node`/`npx` in workspace mode should fall back to `OCD_NODE`'s directory on `PATH` when set (implementation detail for the plan). Python runners rely on the system/interpreter `PATH` as today.

## 6. Safety posture (explicit)
This is **not** a sandbox. The guard rails, in order:
1. **Curated allowlist** — only known runners execute; everything else is rejected (unchanged rejection message lists the allowed set).
2. **Inline-eval block** — the model can't run code it wrote inline via an interpreter.
3. **Mode gate** — runners **prompt in `default`/`acceptEdits`** (HITL) unless the user rule-allows them; `bypass` auto-runs (the user's explicit choice).
4. **Catastrophic-bash breaker** — `rm -rf /`-class hard-denied in every mode.
5. **Single command** — no chaining/redirect/substitution; one command per call.
6. **Workspace arg-jail** — path arguments can't point outside the workspace root.
7. **Bounded** — 120s timeout, 16 KB output cap, secret-scrubbed.

Residual risk (accepted, documented): a runner executes the *project's own* scripts, and prompt-injected repo content could induce a **prompted** runner command. For untrusted repos the answer is the P4 container runner; for the local-first single-user target, prompt-by-default + the user's oversight is the same tradeoff P1 already made for host execution.

## 7. Testing
- **Unit (`run_bash`):** workspace mode runs in `cwd=root` (not `SANDBOX_ROOT`); a runner (`pytest`, `npm`) is accepted; an unlisted command is rejected; `python -c "…"`, `node -e "…"`, and a lone `-` are rejected; `python script.py` is accepted; a path arg outside the workspace is rejected while one inside passes; non-workspace `run_bash` still uses `SANDBOX_ROOT` + `_BASH_ALLOW` (regression). Use a harmless runner (`python --version`, `git --version`) so tests don't depend on a project.
- **Loop-level (`test_agent_workspace.py` pattern):** a workspace turn calling `bash` `pytest` runs in the folder and **prompts** in `default`; an `allow: ["bash(pytest*)"]` rule auto-runs it; `rm -rf /` hard-denies under `bypass`.
- **Process:** per repo convention, an adversarial verify pass on the interpreter-flag guard + arg-jail re-rooting before merge; the existing bash / HITL suites (`test_bash_jail.py`, `test_agent_hitl.py`, `test_permissions.py`) must stay green — non-workspace behaviour is unchanged.

## 8. File structure
- **Modify** `backend/ocd_core/integrations.py` — `run_bash` signature + workspace branch, `WORKSPACE_BASH_ALLOW`, `_INTERPRETERS`/`_INLINE_EVAL_FLAGS`, `_bash_arg_escapes_jail(tok, root)`.
- **Modify** `backend/ocd_core/agent.py` — the `bash` branch of `_run_one_tool` passes `root`/`allow`/`timeout` when `ws` is set; add `WORKSPACE_BASH_TIMEOUT` (or read from `config`).
- **Modify** `backend/ocd_core/config.py` — `WORKSPACE_BASH_TIMEOUT_SEC` (default 120).
- **Tests** `backend/tests/test_bash_jail.py` (extend) + `backend/tests/test_agent_workspace.py` (extend).
- **Docs** one-line update to the Harness README section + the P1 spec's as-built deltas (mark workspace-cwd bash shipped).

## 9. Risks & mitigations
- **Interpreter escape via a wrapper** (`env python -c`, `npx tsx -e`) → `env` and `npx` are **not in the default allowlist** (§4), so this front is blocked at the `parts[0] in allow` check. Adversarial verify still probes for any other allowlisted token that can front an interpreter+eval-flag; if one is found, either scan every token for the interpreter+eval pattern or drop that token.
- **Long/hung process** → 120s timeout kills it; no background mode.
- **PATH gaps in the packaged app** → `OCD_NODE` fallback for node tooling; document that Python-runner availability depends on the host.
- **Over-blocking legitimate args** → flags are exempt and targets resolve-or-not inside the root; adversarial + loop tests confirm common invocations (`npm test`, `npm run build`, `pytest -k`, `cargo test`) pass.

## 10. References
- Harness P1 spec/plan: `docs/superpowers/specs/2026-07-20-harness-design.md` (§14 as-built deltas name this deferral), `docs/superpowers/plans/2026-07-20-harness-phase1.md`.
- In-repo: `integrations.run_bash` / `_BASH_ALLOW` / `_bash_arg_escapes_jail`; `ocd_core/harness/rules.py` (`SAFE_BASH`, `is_catastrophic_bash`); CLAUDE.md "Bash allowlist" note.
