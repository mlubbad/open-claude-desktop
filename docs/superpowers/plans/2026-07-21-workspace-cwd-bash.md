# Workspace-cwd bash Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a workspace-attached agent run build/test **runners** in the attached folder (`cwd=workspace_root`) via a curated allowlist + an inline-eval guard, still behind the existing mode gate + catastrophic-bash breaker; non-workspace bash is byte-for-byte unchanged.

**Architecture:** Two existing layers, one touched. The **execution layer** `integrations.run_bash` gains keyword-only `root`/`allow`/`timeout` params (all defaulting to today's behaviour); the **decision layer** `rules.gate` is untouched (runners stay out of `SAFE_BASH`, so they prompt in `default`/`acceptEdits` unless rule-allowed; the breaker still applies). The agent's `bash` dispatch passes the workspace params when a `ws` context is present.

**Tech Stack:** Python 3.12, `subprocess`/`shlex`, pytest. Spec: `docs/superpowers/specs/2026-07-21-workspace-cwd-bash-design.md`.

**Base:** branch `feat/harness-bash` (stacked on `feat/harness` / PR #102) in worktree `.claude/worktrees/harness-spec`.

**Conventions (read once):**
- Run backend tests from repo root: `.venv\Scripts\python.exe -m pytest backend/tests/test_bash_jail.py -q` (PowerShell). Package imports top-level as `ocd_core`.
- `ruff check backend/ocd_core backend/tests/test_bash_jail.py backend/tests/test_agent_workspace.py` must be clean before each commit (this repo enables E402/I001/B904/F401/E702; merge new imports to the top).
- TDD: failing test → red → minimal impl → green → commit.
- **Baseline noise (do not chase):** ~10 pre-existing Windows-local failures (no Postgres → `test_cowork`; CRLF → `test_workspace`; keyring → `test_providers`) unrelated to this work.

---

## File Structure

**Modify:**
- `backend/ocd_core/config.py` — add `WORKSPACE_BASH_TIMEOUT_SEC`.
- `backend/ocd_core/integrations.py` — `WORKSPACE_BASH_ALLOW`, `_INTERPRETERS`, `_INLINE_EVAL_FLAGS`; parameterize `_bash_arg_escapes_jail(tok, root)`; extend `run_bash(command, restart, *, root, allow, timeout)`.
- `backend/ocd_core/agent.py` — the `bash` branch of `_run_one_tool` (~`:1044`) passes the workspace params when `ws` is set.
- `README.md` + `docs/superpowers/specs/2026-07-20-harness-design.md` — mark workspace-cwd bash shipped.

**Test:**
- `backend/tests/test_bash_jail.py` (extend) — the execution-layer unit tests.
- `backend/tests/test_agent_workspace.py` (extend) — the agent-wiring test.

---

## Task 1: Config + workspace bash constants

**Files:**
- Modify: `backend/ocd_core/config.py`
- Modify: `backend/ocd_core/integrations.py`
- Test: `backend/tests/test_bash_jail.py`

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_bash_jail.py
def test_workspace_bash_constants_exist():
    from ocd_core import config, integrations as ig
    assert config.WORKSPACE_BASH_TIMEOUT_SEC >= 30
    # runners present, read-only base preserved, dangerous fronts absent
    assert {"pytest", "npm", "python", "git"} <= ig.WORKSPACE_BASH_ALLOW
    assert ig._BASH_ALLOW <= ig.WORKSPACE_BASH_ALLOW
    assert not ({"find", "npx", "env"} & ig.WORKSPACE_BASH_ALLOW)
    assert ig._INLINE_EVAL_FLAGS == {"-c", "-e", "--eval", "-"}
    assert {"python", "node"} <= ig._INTERPRETERS
```

- [ ] **Step 2: Run red**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_bash_jail.py::test_workspace_bash_constants_exist -q`
Expected: FAIL — `AttributeError` on `WORKSPACE_BASH_TIMEOUT_SEC` / `WORKSPACE_BASH_ALLOW`.

- [ ] **Step 3: Implement**

In `config.py`, right after `PERMISSION_TIMEOUT_SEC` (`config.py:211`):
```python
# Timeout for bash run in an attached code workspace (builds/tests exceed the 30s
# sandbox default). See docs/superpowers/specs/2026-07-21-workspace-cwd-bash-design.md.
WORKSPACE_BASH_TIMEOUT_SEC = int(os.getenv("OCD_WORKSPACE_BASH_TIMEOUT_SEC", "120"))
```

In `integrations.py`, right after the `_BASH_ALLOW = {...}` definition (`integrations.py:1489-1490`):
```python
# Workspace bash: the read-only base PLUS build/test runners — used ONLY when run_bash
# gets an explicit `allow` (a workspace turn). find/npx/env are deliberately EXCLUDED
# (find -delete/-exec; npx runs arbitrary packages; env fronts an interpreter) — a user
# can add them per-workspace via an `allow` rule. See the workspace-cwd-bash spec.
WORKSPACE_BASH_ALLOW = _BASH_ALLOW | {
    "pytest", "python", "python3", "node", "npm", "pnpm", "yarn",
    "go", "cargo", "make", "tsc", "ruff", "mypy", "eslint", "jest", "vitest",
    "git", "which", "tox", "poetry", "uv",
}
# Interpreters whose inline-eval flags let the MODEL run code it wrote inline → blocked.
_INTERPRETERS = {"python", "python3", "node", "deno", "ruby", "perl", "php"}
_INLINE_EVAL_FLAGS = {"-c", "-e", "--eval", "-"}
```

- [ ] **Step 4: Run green**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_bash_jail.py::test_workspace_bash_constants_exist -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/config.py backend/ocd_core/integrations.py backend/tests/test_bash_jail.py
git commit -m "feat(harness): workspace bash constants (runner allowlist + timeout)"
```

---

## Task 2: Parameterize the arg-jail root

`_bash_arg_escapes_jail` hardcodes `SANDBOX_ROOT`; the workspace needs it rooted at the workspace. Add a `root` parameter defaulting to `SANDBOX_ROOT` so the existing call site keeps working.

**Files:**
- Modify: `backend/ocd_core/integrations.py:1493-1516`
- Test: `backend/tests/test_bash_jail.py`

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_bash_jail.py
def test_arg_escapes_jail_is_root_relative(tmp_path):
    from ocd_core import integrations as ig
    ws = tmp_path / "ws"; ws.mkdir()
    (ws / "tests").mkdir()
    # a path inside the given root is fine; absolute/parent escapes are not
    assert ig._bash_arg_escapes_jail("tests", ws) is False
    assert ig._bash_arg_escapes_jail("tests/unit", ws) is False
    assert ig._bash_arg_escapes_jail("-k", ws) is False          # a flag
    assert ig._bash_arg_escapes_jail("/etc/passwd", ws) is True  # absolute
    assert ig._bash_arg_escapes_jail("../secret", ws) is True    # parent
    # default root still works (back-compat, no root passed)
    assert ig._bash_arg_escapes_jail("-v") is False
```

- [ ] **Step 2: Run red**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_bash_jail.py::test_arg_escapes_jail_is_root_relative -q`
Expected: FAIL — `_bash_arg_escapes_jail()` takes 1 positional arg, not 2.

- [ ] **Step 3: Implement**

Replace `_bash_arg_escapes_jail` (`integrations.py:1493-1516`) with:
```python
def _bash_arg_escapes_jail(tok: str, root: Path | None = None) -> bool:
    """Reject a bash argument that reaches outside ``root`` (default ``SANDBOX_ROOT``).

    The command loop blocks '..' and shell metacharacters, but ABSOLUTE-path arguments
    still escape (e.g. ``cat /etc/passwd``). Flags (leading '-') are fine. Anything that
    looks like an absolute POSIX path, a home-relative path, a Windows drive/UNC path, or
    that resolves outside ``root`` is rejected.
    """
    root = root or SANDBOX_ROOT
    t = (tok or "").strip()
    if not t or t.startswith("-"):
        return False  # empty or a flag — not a path escape
    if t.startswith(("/", "~", "\\")):
        return True
    if len(t) >= 2 and t[1] == ":" and t[0].isalpha():  # C:\ or C:/
        return True
    try:
        target = (root / t).resolve()
        target.relative_to(Path(root).resolve())
        return False
    except Exception:
        return True
```

- [ ] **Step 4: Run green**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_bash_jail.py -q`
Expected: PASS (this test + all pre-existing bash-jail tests still green).

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/integrations.py backend/tests/test_bash_jail.py
git commit -m "refactor(harness): root-parameterize _bash_arg_escapes_jail"
```

---

## Task 3: `run_bash` workspace mode

Add keyword-only `root`/`allow`/`timeout` (all default to today's behaviour) + the inline-eval guard, re-rooted arg-jail, and mode-generic messages.

**Files:**
- Modify: `backend/ocd_core/integrations.py:2097-2133`
- Test: `backend/tests/test_bash_jail.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_bash_jail.py
from ocd_core import integrations as ig

# Use `python` for the execution tests — always present in the venv and portable across
# Windows/Linux (unlike `ls`/`pwd`, which aren't reliable subprocess binaries on Windows).


def test_run_bash_workspace_runs_script_in_root(tmp_path):
    # A runner (python) executes a workspace script FILE with cwd=root — proves both that
    # the runner allowlist is honored and that cwd is the workspace (script prints getcwd).
    (tmp_path / "cwd.py").write_text("import os\nprint(os.getcwd())\n")
    out = ig.run_bash("python cwd.py", root=tmp_path, allow=ig.WORKSPACE_BASH_ALLOW, timeout=30)
    assert tmp_path.name in out          # ran in the workspace dir
    assert "Rejected" not in out


def test_run_bash_workspace_blocks_inline_eval(tmp_path):
    out = ig.run_bash('python -c "print(1)"', root=tmp_path,
                      allow=ig.WORKSPACE_BASH_ALLOW, timeout=30)
    assert "inline code" in out.lower() and "rejected" in out.lower()


def test_run_bash_workspace_rejects_unlisted(tmp_path):
    out = ig.run_bash("rm -rf x", root=tmp_path, allow=ig.WORKSPACE_BASH_ALLOW, timeout=30)
    assert "not allowlisted" in out.lower()


def test_run_bash_workspace_rejects_outside_arg(tmp_path):
    # cat is in the read-only base (allowed); the arg-jail rejects the absolute path
    # BEFORE any subprocess runs, so this is portable (no dependency on `cat` existing).
    out = ig.run_bash("cat /etc/passwd", root=tmp_path, allow=ig.WORKSPACE_BASH_ALLOW, timeout=30)
    assert "outside" in out.lower() and "rejected" in out.lower()


def test_run_bash_nonworkspace_unchanged():
    # no root/allow -> read-only base + SANDBOX_ROOT (regression): a runner is NOT allowed
    out = ig.run_bash("pytest")
    assert "not allowlisted" in out.lower()
```

- [ ] **Step 2: Run red**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_bash_jail.py -k workspace -q`
Expected: FAIL — `run_bash()` got an unexpected keyword argument `root`.

- [ ] **Step 3: Implement**

Replace `run_bash` (`integrations.py:2097-2133`) with:
```python
def run_bash(command: str, restart: bool = False, *,
             root: "Path | None" = None, allow: "set | None" = None,
             timeout: int | None = None) -> str:
    import shlex
    import subprocess
    active_root = Path(root) if root is not None else SANDBOX_ROOT
    active_allow = allow if allow is not None else _BASH_ALLOW
    active_timeout = timeout if timeout is not None else 30
    _ensure_dir(active_root)
    if restart:
        return "Bash session restarted."
    command = (command or "").strip()
    if not command:
        return "Rejected: empty command."
    if any(tok in command for tok in ("&&", "||", "|", ";", "&", ">", "<", "`",
                                      "$(", "${", "..", "\n")):
        return ("Rejected: pipes, redirects, chaining, and path traversal are not "
                "allowed. Run one simple allowlisted command.")
    try:
        parts = shlex.split(command)
    except Exception:
        return "Rejected: could not parse command."
    if not parts or parts[0] not in active_allow:
        return (f"Rejected: '{parts[0] if parts else ''}' is not allowlisted. Allowed: "
                + ", ".join(sorted(active_allow)))
    # Interpreters may run the workspace's own script FILES, but not code the model wrote
    # inline (-c/-e/--eval/stdin). Unreachable in non-workspace mode (interpreters aren't
    # in _BASH_ALLOW), so this is safe to apply unconditionally.
    if parts[0] in _INTERPRETERS and any(a in _INLINE_EVAL_FLAGS for a in parts[1:]):
        return ("Rejected: inline code (-c/-e/--eval/stdin) is not allowed. Run a file in "
                "the workspace instead (e.g. `python script.py`).")
    # No argument may point outside the active root (blocks `cat /etc/passwd` etc.).
    escaping = next((a for a in parts[1:] if _bash_arg_escapes_jail(a, active_root)), None)
    if escaping is not None:
        return ("Rejected: argument outside the workspace is not allowed "
                f"('{escaping}'). Only paths inside the working directory are permitted.")
    try:
        proc = subprocess.run(parts, cwd=str(active_root), capture_output=True,
                              text=True, timeout=active_timeout, shell=False)
        out = (proc.stdout or "") + (proc.stderr or "")
        return _scrub_secrets(_cap(out, 16000)) or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Timed out after {active_timeout}s."
    except FileNotFoundError:
        return f"Rejected: '{parts[0]}' is not available on this system."
    except Exception as e:
        return f"Error: {str(e)[:200]}"
```

- [ ] **Step 4: Run green**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_bash_jail.py -q`
Expected: PASS (new workspace tests + all pre-existing bash-jail tests). The execution tests use `python` (always present in the venv, portable) — do not switch them to `pytest`/`ls`/`pwd`, which may be absent as subprocess binaries on some hosts.

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/integrations.py backend/tests/test_bash_jail.py
git commit -m "feat(harness): run_bash workspace mode (cwd=root, runner allowlist, inline-eval guard)"
```

---

## Task 4: Wire workspace bash into the agent loop

**Files:**
- Modify: `backend/ocd_core/agent.py` (the `bash` branch of `_run_one_tool`, ~`:1044`)
- Test: `backend/tests/test_agent_workspace.py`

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_agent_workspace.py
def test_workspace_bash_passes_root_and_allow(monkeypatch, tmp_path):
    """In a workspace turn, the bash tool calls run_bash with the workspace root,
    the runner allowlist, and the workspace timeout."""
    from ocd_core import integrations, config

    captured = {}

    def _fake_run_bash(command, restart=False, *, root=None, allow=None, timeout=None):
        captured.update(command=command, root=root, allow=allow, timeout=timeout)
        return "ran"

    monkeypatch.setattr(integrations, "run_bash", _fake_run_bash)

    calls = iter([[_FakeToolCall("c1", "bash", '{"command": "pytest -q"}')], []])

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        try:
            tcs = next(calls)
        except StopIteration:
            tcs = []
        if tcs:
            yield {"__done__": {"content": "", "note": None, "tool_calls": tcs}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "done"}
            yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        events = []
        async for ev in agent.run_turn("test it", [], None, "m", effort="Low", bash=True,
                                       workspace_root=str(tmp_path),
                                       permission_mode="bypass", turn_id="t1"):
            events.append(ev)
        return events

    asyncio.run(scenario())
    assert captured["root"] == str(tmp_path)
    assert captured["allow"] is integrations.WORKSPACE_BASH_ALLOW
    assert captured["timeout"] == config.WORKSPACE_BASH_TIMEOUT_SEC
```

(Note: `permission_mode="bypass"` so the gate auto-allows `bash` and the call reaches `run_bash`; `bash=True` enables the tool.)

- [ ] **Step 2: Run red**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_agent_workspace.py::test_workspace_bash_passes_root_and_allow -q`
Expected: FAIL — `captured` is empty / `root` is None (run_bash called without workspace params).

- [ ] **Step 3: Implement**

In `agent.py`, replace the `bash` branch of `_run_one_tool` (~`:1044-1051`):
```python
        if name == "bash":
            from . import integrations
            if ws is not None:
                result = await asyncio.to_thread(
                    integrations.run_bash, args.get("command", ""),
                    bool(args.get("restart")), root=ws["root"],
                    allow=integrations.WORKSPACE_BASH_ALLOW,
                    timeout=config.WORKSPACE_BASH_TIMEOUT_SEC)
            else:
                result = await asyncio.to_thread(integrations.run_bash,
                                                 args.get("command", ""),
                                                 bool(args.get("restart")))
            ok = not result.startswith(("Rejected:", "Error:", "Timed out"))
            out = {"id": tc_id, "name": name, "ok": ok, "result": result,
                   "summary": result[:300]}
            if not ok:
                out["error"] = result
            return out
```
(`config` is already imported in `agent.py`; `ws` is already a `_run_one_tool` param from P1.)

- [ ] **Step 4: Run green (+ regression)**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_agent_workspace.py backend/tests/test_agent_hitl.py backend/tests/test_permissions.py -q`
Expected: PASS (new test green; existing HITL/workspace/permission tests unaffected).

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/agent.py backend/tests/test_agent_workspace.py
git commit -m "feat(harness): run workspace bash in the attached folder (agent wiring)"
```

---

## Task 5: Adversarial verify + docs + full gate

- [ ] **Step 1: Full backend gate**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_bash_jail.py backend/tests/test_agent_workspace.py backend/tests/test_agent_hitl.py backend/tests/test_permissions.py backend/tests/test_harness_rules.py -q`
Expected: PASS. Then `ruff check backend/ocd_core backend/tests/test_bash_jail.py backend/tests/test_agent_workspace.py` → clean.

- [ ] **Step 2: Adversarial verify (subagent)**

**Already fixed during Task 3 review (commit `fix(harness): harden workspace bash guard …`):** the `uv/poetry run python -c` interpreter-front, the bare-interpreter REPL (`python` with no args), and the missing-workspace-root fabrication were all found in the Task-3 two-stage review and fixed there — the guard now scans ALL tokens for an interpreter followed by an inline-eval flag (or a bare interpreter), and a missing `root` errors instead of being `mkdir`'d. So this step is now **confirm + probe-for-more**, not the primary fix.

Dispatch a fresh subagent to CONFIRM those are closed and hunt for anything else: `--command=`-joined eval forms (confirm the interpreter only treats `-c`/`-e`); a path arg that resolves inside via a symlink pointing OUT of the workspace (does `.resolve()` in `_bash_arg_escapes_jail` catch it?); `python -m http.server` and other long-runners (must hit the timeout, not hang — use a short timeout in the probe); `go run`/`make`/`npm run <script>` invoking a shell that then does something outside (single-command ban should stop chaining, but confirm). Any NEW real escape → add a failing test and fix. Record the outcome ("guard HOLDS across N classes") in the commit body.

- [ ] **Step 3: Docs**

In `README.md`, update the Harness bash line — replace the "(`bash` remains the existing read-only … not P1.)" parenthetical with:
```
- **Run in the folder** — in a workspace, `bash` runs build/test **runners** (`pytest`,
  `npm test`, `cargo test`, …) in the attached folder via a curated allowlist; interpreters
  run the repo's own script files but inline `-c`/`-e` is blocked. Runners prompt by default
  (`allow` a command to auto-run it); `rm -rf /`-class stays hard-blocked.
```
In `docs/superpowers/specs/2026-07-20-harness-design.md`, change the "`bash` cwd is NOT the workspace in P1" as-built bullet to note it shipped in the P1.5 fast-follow (cite this spec/branch). Also update `SECURITY.md` (~`:44-45`) — its "`bash` is allowlisted and path-jailed to a sandbox; `python` is not allowlisted" line now needs a clause: in an attached workspace, `bash` additionally allows curated build/test runners (incl. `python`/`node` on the repo's own script files, inline `-c`/`-e` blocked) in the workspace cwd, behind the mode gate + catastrophic breaker.

- [ ] **Step 4: Commit**

```bash
git add -A backend/ README.md docs/superpowers/specs/2026-07-20-harness-design.md SECURITY.md
git commit -m "test(harness): adversarial-verify workspace bash + docs (shipped)"
```

- [ ] **Step 5: Deliver**

Rebase onto the base once P1 (PR #102) merges (`git rebase origin/main`), push `feat/harness-bash`, and open a PR against `main` linking this spec. If P1 is not yet merged, keep the branch stacked and open the PR with base `feat/harness` (note the stack in the PR body).

---

## Self-Review Notes (for the executor)

- **Spec coverage:** §3 execution layer → Tasks 2-3; §3 agent wiring → Task 4; §4 allowlist + interpreter guard → Tasks 1, 3; §4 arg-jail re-rooting → Task 2; §5 timeout/config → Task 1; §6 safety (single-command ban, breaker) → unchanged/verified in Task 5; §7 testing → every task + Task 5; §9 interpreter-front risk → Task 5 Step 2 (explicitly probed).
- **Decision layer untouched:** no change to `rules.py` — runners are absent from `SAFE_BASH`, so `rules.gate` already returns `ask` for them in `default`/`acceptEdits` and `allow` in `bypass`, and `is_catastrophic_bash` already hard-denies. If a reviewer wants a test locking this in, add: `rules.gate("bash", {"command": "pytest"}, "acceptEdits", RuleSet()) == "ask"` and `... "bypass" ... == "allow"`.
- **Not in scope (do not add):** shell chaining/pipes/redirects, background processes, per-workspace configurable command lists, the container sandbox, any desktop change.
- **Highest-risk task:** Task 5's adversarial pass on the interpreter-front (`poetry run python -c`) — treat a confirmed front as a must-fix before delivery.
