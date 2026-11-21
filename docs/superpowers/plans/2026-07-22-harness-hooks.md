# Harness P2a — Hooks — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the harness user-owned, deterministic lifecycle hooks — shell commands the app runs at five agent-loop events (Claude's JSON stdin/stdout contract), able to inject context, block a turn, or tighten a tool decision.

**Architecture:** One new module `backend/ocd_core/harness/hooks.py` owns matching, execution, timeout, and decision parsing; `agent.py` gets five small `await hooks.run(...)` call sites. Hooks come from app settings only (never a workspace folder), run `shell=False` with a sanitized env, fail **closed** on `PreToolUse` and **open** on observational events, and can only ever tighten an existing decision — never loosen one.

**Tech Stack:** Python 3.12, `asyncio`/`subprocess`/`shlex`/`json`, pytest. Spec: `docs/superpowers/specs/2026-07-22-harness-hooks-design.md`.

**Base:** branch `feat/harness-hooks` in worktree `.claude/worktrees/harness-hooks`, based on `origin/main` @ `f794444` (P1 #102 + P1.5 bash #103 merged).

**Conventions (read once):**
- Run backend tests from the repo root: `.venv\Scripts\python.exe -m pytest backend/tests/test_harness_hooks.py -q` (PowerShell). Package imports top-level as `ocd_core` (never `backend.ocd_core`).
- `ruff check backend/ocd_core backend/tests/<the test files>` must be clean before each commit (this repo enables E402/I001/B904/F401/E702/UP037; merge new imports to the top of the file, in isort order).
- TDD per task: failing test → run red → minimal implementation → run green → commit.
- **Portability:** hook-execution tests must invoke `python <script>` (a real binary on Windows and Linux). Never `echo`/`ls`/`pwd` — they are shell builtins, not standalone binaries on Windows, and `echo` already fails on this host.
- **Baseline noise (do not chase):** ~10 pre-existing Windows-local failures (no Postgres → `test_cowork`; CRLF → `test_workspace`; keyring → `test_providers`; `echo` → `test_bash_jail::test_run_bash_still_allows_safe_relative`). None are yours.

**Verified integration anchors** (confirmed against this worktree — line numbers are real):
| What | Where |
|---|---|
| `extra_sections = []` (SessionStart context lands here) | `agent.py:1304` |
| `user_content` built, then `messages = [...]` (UserPromptSubmit) | `agent.py:1330-1356` |
| Existing HITL gate `if gate_on and not domain_gate_prompted and permissions.requires_approval(...)` (PreToolUse goes immediately before) | `agent.py:1757` |
| `for ev in _completion_events(out, streamed)` in the drain loop (PostToolUse goes after) | `agent.py:1813` |
| Turn finalize (`answer_shown = True`, `final_text`) — Stop fires before the final yield | `agent.py:1886-1891`, `:1920-1924` |
| `DEFAULT_SETTINGS` | `config.py:112` |
| `_sanitized_child_env()` (hooks reuse it) | `integrations.py:2154` |

---

## File Structure

**Create:**
- `backend/ocd_core/harness/hooks.py` — the whole hook subsystem: `HookDecision`, `load_hooks`, `matches`, `run`.
- `backend/tests/test_harness_hooks.py` — unit tests for the runner.

**Modify:**
- `backend/ocd_core/config.py` — `DEFAULT_SETTINGS["hooks"] = {}` + timeout constants.
- `backend/ocd_core/agent.py` — five call sites.
- `backend/tests/test_agent_workspace.py` — loop-level tests.
- `README.md`, `SECURITY.md`, `docs/superpowers/specs/2026-07-20-harness-design.md` — docs (Task 7).

---

## Task 1: Config keys + hook loading

**Files:**
- Modify: `backend/ocd_core/config.py:112` (DEFAULT_SETTINGS)
- Create: `backend/ocd_core/harness/hooks.py`
- Test: `backend/tests/test_harness_hooks.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_harness_hooks.py
from ocd_core import config
from ocd_core.harness import hooks


def test_config_defaults():
    assert config.DEFAULT_SETTINGS["hooks"] == {}
    assert config.HOOK_TIMEOUT_SEC == 30
    assert config.HOOK_TIMEOUT_MAX_SEC == 120


def test_events_are_the_five_v1_events():
    assert hooks.EVENTS == ("SessionStart", "UserPromptSubmit", "PreToolUse",
                            "PostToolUse", "Stop")


def test_load_hooks_empty_when_unconfigured(monkeypatch):
    monkeypatch.setattr(hooks.settings, "get_settings", lambda: {})
    assert hooks.load_hooks("PreToolUse") == []


def test_load_hooks_returns_configured_list(monkeypatch):
    cfg = {"hooks": {"PreToolUse": [{"matcher": "bash", "command": "python x.py"}]}}
    monkeypatch.setattr(hooks.settings, "get_settings", lambda: cfg)
    got = hooks.load_hooks("PreToolUse")
    assert len(got) == 1 and got[0]["command"] == "python x.py"


def test_load_hooks_ignores_unknown_event_and_bad_shapes(monkeypatch):
    cfg = {"hooks": {"NotAnEvent": [{"command": "x"}],
                     "PreToolUse": ["not-a-dict", {"no_command": 1}]}}
    monkeypatch.setattr(hooks.settings, "get_settings", lambda: cfg)
    assert hooks.load_hooks("NotAnEvent") == []      # unknown event
    assert hooks.load_hooks("PreToolUse") == []      # both entries invalid -> dropped
```

- [ ] **Step 2: Run red**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_harness_hooks.py -q`
Expected: FAIL — `ModuleNotFoundError: ocd_core.harness.hooks` / no `HOOK_TIMEOUT_SEC`.

- [ ] **Step 3: Implement**

In `config.py`, add inside `DEFAULT_SETTINGS` (after the `"permission_mode"` entry at `config.py:133`):
```python
                    # Lifecycle hooks (harness P2a): {event: [{matcher, command, timeout}]}.
                    # APP-OWNED ONLY — never loaded from a workspace folder, because a hook
                    # EXECUTES (unlike workspace permission rules, which only restrict).
                    "hooks": {},
```
and after the `DEFAULT_SETTINGS` block:
```python
# Hook execution bounds (harness P2a).
HOOK_TIMEOUT_SEC = int(os.getenv("OCD_HOOK_TIMEOUT_SEC", "30"))
HOOK_TIMEOUT_MAX_SEC = int(os.getenv("OCD_HOOK_TIMEOUT_MAX_SEC", "120"))
HOOK_OUTPUT_MAX_CHARS = 8000
```

Create `backend/ocd_core/harness/hooks.py`:
```python
"""Harness lifecycle hooks — deterministic, user-owned interception points.

A hook is a shell command run at a lifecycle event: it receives the event as JSON on
stdin and returns a decision on stdout (or via its exit code). Hooks run OUTSIDE the
model's context — they cost no tokens and the model cannot argue with them.

Security posture (see docs/superpowers/specs/2026-07-22-harness-hooks-design.md):
  * Hooks come from APP SETTINGS ONLY — never from a workspace's .claude/settings.json.
    A workspace may contribute permission RULES (which only restrict); a hook EXECUTES.
  * PreToolUse fails CLOSED (timeout/crash/garbage -> deny); observational events fail OPEN.
  * A hook can only TIGHTEN a decision, never loosen one (see agent.py's gate ordering).
"""
from __future__ import annotations

from dataclasses import dataclass

from .. import config, settings

EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")
#: Events whose failure must BLOCK (fail closed). Everything else is observational.
BLOCKING_EVENTS = ("PreToolUse", "UserPromptSubmit")


@dataclass
class HookDecision:
    """Merged outcome of every hook that matched an event."""
    decision: str | None = None      # "allow" | "deny" | "ask" | None (no opinion)
    reason: str = ""
    context: str = ""                # additionalContext to inject

    @property
    def denied(self) -> bool:
        return self.decision == "deny"


def load_hooks(event: str) -> list[dict]:
    """Hook configs for ``event`` from app settings. Returns [] when unconfigured or
    malformed — a bad config must never crash a turn."""
    if event not in EVENTS:
        return []
    try:
        raw = (settings.get_settings() or {}).get("hooks") or {}
        entries = raw.get(event) or []
    except Exception:
        return []
    out = []
    for e in entries if isinstance(entries, list) else []:
        if isinstance(e, dict) and str(e.get("command") or "").strip():
            out.append(e)
    return out
```

- [ ] **Step 4: Run green**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_harness_hooks.py -q`
Expected: PASS (5 tests). Then `.venv\Scripts\python.exe -m ruff check backend/ocd_core backend/tests/test_harness_hooks.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/config.py backend/ocd_core/harness/hooks.py backend/tests/test_harness_hooks.py
git commit -m "feat(harness): hook config keys + loader"
```

---

## Task 2: Matcher

**Files:**
- Modify: `backend/ocd_core/harness/hooks.py`
- Test: `backend/tests/test_harness_hooks.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_harness_hooks.py
def test_matches_star_and_missing_matcher():
    assert hooks.matches({"matcher": "*", "command": "x"}, "bash") is True
    assert hooks.matches({"command": "x"}, "bash") is True          # omitted = all
    assert hooks.matches({"matcher": "", "command": "x"}, "bash") is True


def test_matches_regex_alternation():
    h = {"matcher": "bash|edit_file", "command": "x"}
    assert hooks.matches(h, "bash") is True
    assert hooks.matches(h, "edit_file") is True
    assert hooks.matches(h, "read_file") is False


def test_matches_is_anchored_not_substring():
    # "edit" must NOT match "edit_file" — a matcher names a tool, not a prefix.
    assert hooks.matches({"matcher": "edit", "command": "x"}, "edit_file") is False


def test_matches_bad_regex_is_false_not_raise():
    assert hooks.matches({"matcher": "[unclosed", "command": "x"}, "bash") is False


def test_matches_true_when_no_tool_name():
    # non-tool events (SessionStart/Stop/UserPromptSubmit) ignore the matcher
    assert hooks.matches({"matcher": "bash", "command": "x"}, None) is True
```

- [ ] **Step 2: Run red**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_harness_hooks.py -q`
Expected: FAIL — module has no attribute `matches`.

- [ ] **Step 3: Implement**

Add `import re` to the top import block of `hooks.py` (stdlib group, before the `from dataclasses` line), then append:
```python
def matches(hook: dict, tool_name: str | None) -> bool:
    """Does ``hook``'s matcher apply to ``tool_name``? A missing/empty/``*`` matcher
    matches everything; otherwise it is a FULLY-ANCHORED regex on the tool name (so
    "edit" does not match "edit_file"). Non-tool events pass tool_name=None and always
    match. A malformed regex matches nothing (fail closed toward not-running the hook)."""
    if tool_name is None:
        return True
    m = str(hook.get("matcher") or "").strip()
    if not m or m == "*":
        return True
    try:
        return re.fullmatch(m, tool_name) is not None
    except re.error:
        return False
```

- [ ] **Step 4: Run green**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_harness_hooks.py -q`
Expected: PASS (10 tests). Ruff clean.

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/harness/hooks.py backend/tests/test_harness_hooks.py
git commit -m "feat(harness): hook matcher (anchored regex on tool name)"
```

---

## Task 3: Decision parsing + merge

Pure functions, no subprocess — so the semantics are testable in isolation before execution lands.

**Files:**
- Modify: `backend/ocd_core/harness/hooks.py`
- Test: `backend/tests/test_harness_hooks.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_harness_hooks.py
def test_parse_json_decision():
    d = hooks.parse_output(0, '{"permissionDecision":"deny","reason":"nope"}', "", "PreToolUse")
    assert d.decision == "deny" and d.reason == "nope"


def test_parse_json_context_only():
    d = hooks.parse_output(0, '{"additionalContext":"remember X"}', "", "SessionStart")
    assert d.decision is None and d.context == "remember X"


def test_parse_exit_zero_non_json_is_no_opinion():
    d = hooks.parse_output(0, "just some log text", "", "PreToolUse")
    assert d.decision is None and d.context == ""


def test_parse_exit_two_is_deny_with_stderr_reason():
    d = hooks.parse_output(2, "", "policy says no", "PreToolUse")
    assert d.decision == "deny" and "policy says no" in d.reason


def test_parse_other_nonzero_denies_for_blocking_event():
    d = hooks.parse_output(1, "", "boom", "PreToolUse")
    assert d.decision == "deny"          # fail CLOSED


def test_parse_other_nonzero_is_no_opinion_for_observational_event():
    d = hooks.parse_output(1, "", "boom", "PostToolUse")
    assert d.decision is None            # fail OPEN


def test_parse_malformed_json_denies_for_blocking_event():
    d = hooks.parse_output(0, '{"permissionDecision": ', "", "PreToolUse")
    assert d.decision == "deny"


def test_parse_malformed_json_is_no_opinion_for_observational_event():
    assert hooks.parse_output(0, '{"nope": ', "", "Stop").decision is None


def test_parse_unknown_decision_value_denies_for_blocking_event():
    d = hooks.parse_output(0, '{"permissionDecision":"banana"}', "", "PreToolUse")
    assert d.decision == "deny"


def test_merge_strictest_wins():
    a = hooks.HookDecision(decision="allow")
    b = hooks.HookDecision(decision="ask")
    c = hooks.HookDecision(decision="deny", reason="r")
    assert hooks.merge([a, b]).decision == "ask"
    assert hooks.merge([a, b, c]).decision == "deny"
    assert hooks.merge([a]).decision == "allow"
    assert hooks.merge([]).decision is None


def test_merge_concatenates_context():
    out = hooks.merge([hooks.HookDecision(context="one"), hooks.HookDecision(context="two")])
    assert "one" in out.context and "two" in out.context
```

- [ ] **Step 2: Run red**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_harness_hooks.py -q`
Expected: FAIL — no attribute `parse_output` / `merge`.

- [ ] **Step 3: Implement**

Add `import json` to the top import block of `hooks.py` (stdlib group, alphabetically before `re`), then append:
```python
_VALID_DECISIONS = ("allow", "deny", "ask")
#: Strictness order — a later entry beats an earlier one when hooks disagree.
_STRICTNESS = {None: 0, "allow": 1, "ask": 2, "deny": 3}


def _fail(event: str, reason: str) -> HookDecision:
    """A hook failure: deny for a blocking event (fail closed), no-opinion otherwise."""
    if event in BLOCKING_EVENTS:
        return HookDecision(decision="deny", reason=reason)
    return HookDecision(reason=reason)


def parse_output(code: int, stdout: str, stderr: str, event: str) -> HookDecision:
    """Turn one hook's exit code + streams into a decision.

    exit 0 + JSON  -> that decision/context;  exit 0 + non-JSON -> no opinion
    exit 2         -> deny (stderr is the reason)
    other non-zero -> deny for a blocking event, else no opinion
    """
    out = (stdout or "").strip()[:config.HOOK_OUTPUT_MAX_CHARS]
    err = (stderr or "").strip()[:config.HOOK_OUTPUT_MAX_CHARS]
    if code == 2:
        return HookDecision(decision="deny", reason=err or "hook exited 2 (blocked)")
    if code != 0:
        return _fail(event, f"hook failed (exit {code}): {err or 'no stderr'}")
    if not out.startswith("{"):
        return HookDecision()                      # plain log output — no opinion
    try:
        data = json.loads(out)
    except ValueError:
        return _fail(event, "hook emitted malformed JSON")
    if not isinstance(data, dict):
        return _fail(event, "hook JSON was not an object")
    dec = data.get("permissionDecision")
    if dec is not None and dec not in _VALID_DECISIONS:
        return _fail(event, f"hook returned an unknown decision: {dec!r}")
    return HookDecision(decision=dec, reason=str(data.get("reason") or ""),
                        context=str(data.get("additionalContext") or ""))


def merge(decisions: list) -> HookDecision:
    """Combine several hooks' outcomes: the STRICTEST decision wins; contexts concatenate."""
    best = HookDecision()
    ctx, reasons = [], []
    for d in decisions:
        if _STRICTNESS.get(d.decision, 0) > _STRICTNESS.get(best.decision, 0):
            best = HookDecision(decision=d.decision, reason=d.reason)
        if d.context:
            ctx.append(d.context)
        if d.reason:
            reasons.append(d.reason)
    return HookDecision(decision=best.decision,
                        reason=best.reason or "; ".join(reasons),
                        context="\n".join(ctx))
```

- [ ] **Step 4: Run green**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_harness_hooks.py -q`
Expected: PASS (21 tests). Ruff clean.

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/harness/hooks.py backend/tests/test_harness_hooks.py
git commit -m "feat(harness): hook decision parsing + strictest-wins merge"
```

---

## Task 4: The runner (`run`)

**Files:**
- Modify: `backend/ocd_core/harness/hooks.py`
- Test: `backend/tests/test_harness_hooks.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_harness_hooks.py
import asyncio
import json as _json
import sys


def _hook_settings(monkeypatch, event, command, matcher="*", timeout=None):
    entry = {"matcher": matcher, "command": command}
    if timeout is not None:
        entry["timeout"] = timeout
    monkeypatch.setattr(hooks.settings, "get_settings", lambda: {"hooks": {event: [entry]}})


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def test_run_no_hooks_configured_spawns_nothing(monkeypatch):
    monkeypatch.setattr(hooks.settings, "get_settings", lambda: {})
    called = []
    monkeypatch.setattr(hooks.asyncio, "create_subprocess_exec",
                        lambda *a, **k: called.append(a))
    d = asyncio.run(hooks.run("PreToolUse", {"tool_name": "bash"}))
    assert d.decision is None and called == []


def test_run_reads_payload_on_stdin_and_denies(monkeypatch, tmp_path):
    # the hook echoes a deny only if it actually received the tool name on stdin
    s = _write(tmp_path, "deny.py",
               "import json,sys\n"
               "p=json.load(sys.stdin)\n"
               "print(json.dumps({'permissionDecision':'deny','reason':'saw '+p['tool_name']}))\n")
    _hook_settings(monkeypatch, "PreToolUse", f'"{sys.executable}" "{s}"')
    d = asyncio.run(hooks.run("PreToolUse", {"tool_name": "bash", "tool_input": {}}))
    assert d.decision == "deny" and "saw bash" in d.reason


def test_run_matcher_filters(monkeypatch, tmp_path):
    s = _write(tmp_path, "deny.py",
               "import sys,json; print(json.dumps({'permissionDecision':'deny'}))\n")
    _hook_settings(monkeypatch, "PreToolUse", f'"{sys.executable}" "{s}"', matcher="edit_file")
    d = asyncio.run(hooks.run("PreToolUse", {"tool_name": "bash"}))
    assert d.decision is None          # matcher didn't match -> hook never ran


def test_run_timeout_denies_blocking_event(monkeypatch, tmp_path):
    s = _write(tmp_path, "hang.py", "import time; time.sleep(30)\n")
    _hook_settings(monkeypatch, "PreToolUse", f'"{sys.executable}" "{s}"', timeout=1)
    d = asyncio.run(hooks.run("PreToolUse", {"tool_name": "bash"}))
    assert d.decision == "deny" and "timed out" in d.reason.lower()


def test_run_timeout_is_open_for_observational_event(monkeypatch, tmp_path):
    s = _write(tmp_path, "hang.py", "import time; time.sleep(30)\n")
    _hook_settings(monkeypatch, "PostToolUse", f'"{sys.executable}" "{s}"', timeout=1)
    d = asyncio.run(hooks.run("PostToolUse", {"tool_name": "bash"}))
    assert d.decision is None


def test_run_missing_command_denies_blocking_event(monkeypatch):
    _hook_settings(monkeypatch, "PreToolUse", "definitely-not-a-real-binary-xyz")
    d = asyncio.run(hooks.run("PreToolUse", {"tool_name": "bash"}))
    assert d.decision == "deny"


def test_run_strips_secret_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OCD_API_TOKEN", "TOKLEAK-hook")
    s = _write(tmp_path, "env.py",
               "import os,json\n"
               "print(json.dumps({'additionalContext': 'tok=' + os.environ.get('OCD_API_TOKEN','')}))\n")
    _hook_settings(monkeypatch, "SessionStart", f'"{sys.executable}" "{s}"')
    d = asyncio.run(hooks.run("SessionStart", {}))
    assert "TOKLEAK-hook" not in d.context and "tok=" in d.context


def test_run_caps_timeout_at_max(monkeypatch, tmp_path):
    s = _write(tmp_path, "ok.py", "print('{}')\n")
    _hook_settings(monkeypatch, "SessionStart", f'"{sys.executable}" "{s}"', timeout=99999)
    # must not raise; the cap is applied internally
    assert asyncio.run(hooks.run("SessionStart", {})).decision is None
```

- [ ] **Step 2: Run red**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_harness_hooks.py -q`
Expected: FAIL — no attribute `run`.

- [ ] **Step 3: Implement**

Add `import asyncio` and `import shlex` to `hooks.py`'s top import block (stdlib group, isort order: `asyncio`, `json`, `re`, `shlex`), then append:
```python
def _timeout_for(hook: dict) -> int:
    try:
        t = int(hook.get("timeout") or config.HOOK_TIMEOUT_SEC)
    except (TypeError, ValueError):
        t = config.HOOK_TIMEOUT_SEC
    return max(1, min(t, config.HOOK_TIMEOUT_MAX_SEC))


async def _run_one(hook: dict, event: str, payload: dict, cwd: str | None) -> HookDecision:
    """Execute ONE hook. Never raises — every failure becomes a HookDecision."""
    from .. import integrations, observability
    cmd = str(hook.get("command") or "")
    timeout = _timeout_for(hook)
    try:
        parts = shlex.split(cmd, posix=False)
    except ValueError:
        return _fail(event, f"hook command could not be parsed: {cmd!r}")
    if not parts:
        return _fail(event, "hook command was empty")
    # posix=False keeps Windows paths intact but leaves quotes on tokens — strip them.
    parts = [p.strip('"') for p in parts]
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *parts, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=cwd,
            env=integrations._sanitized_child_env())
        raw = json.dumps({"event": event, **payload}).encode("utf-8")
        out_b, err_b = await asyncio.wait_for(proc.communicate(raw), timeout=timeout)
        decision = parse_output(proc.returncode, out_b.decode("utf-8", "replace"),
                                err_b.decode("utf-8", "replace"), event)
    except asyncio.TimeoutError:
        if proc is not None:
            try:
                proc.kill()
            except OSError:
                pass
        decision = _fail(event, f"hook timed out after {timeout}s: {cmd}")
    except (OSError, ValueError) as e:                 # not found, bad exe, etc.
        decision = _fail(event, f"hook could not run ({e}): {cmd}")
    # Scrub anything secret-shaped a hook printed before it reaches the model or the log.
    decision.reason = integrations._scrub_secrets(decision.reason)
    decision.context = integrations._scrub_secrets(decision.context)
    observability.audit({"event": "hook_run", "hook_event": event,
                         "command": cmd, "tool": payload.get("tool_name"),
                         "decision": decision.decision or "none"})
    return decision


async def run(event: str, payload: dict, cwd: str | None = None) -> HookDecision:
    """Run every hook matching ``event`` (and the payload's tool_name) and merge the
    results. Returns a no-opinion decision when nothing is configured — costing no
    subprocess and leaving the turn byte-for-byte as it was before hooks existed."""
    configured = load_hooks(event)
    if not configured:
        return HookDecision()
    tool = payload.get("tool_name")
    applicable = [h for h in configured if matches(h, tool)]
    if not applicable:
        return HookDecision()
    results = [await _run_one(h, event, payload, cwd) for h in applicable]
    return merge(results)
```

- [ ] **Step 4: Run green**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_harness_hooks.py -q`
Expected: PASS (29 tests). Ruff clean.

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/harness/hooks.py backend/tests/test_harness_hooks.py
git commit -m "feat(harness): hook runner (stdin JSON, timeout, sanitized env, audited)"
```

---

## Task 5: Wire the two blocking call sites (`PreToolUse`, `UserPromptSubmit`)

The security-critical wiring. Do it before the observational ones and re-run the HITL suite.

**Files:**
- Modify: `backend/ocd_core/agent.py` (~`:1330-1356` and `:1757`)
- Test: `backend/tests/test_agent_workspace.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_agent_workspace.py
def _fake_stream_factory(calls):
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
    return _fake_stream


def test_pretooluse_hook_denies_tool(monkeypatch, tmp_path):
    """A PreToolUse deny blocks the tool and the model sees the reason."""
    from ocd_core.harness import hooks

    async def _fake_run(event, payload, cwd=None):
        if event == "PreToolUse":
            return hooks.HookDecision(decision="deny", reason="blocked by my gate")
        return hooks.HookDecision()

    monkeypatch.setattr(hooks, "run", _fake_run)
    (tmp_path / "a.txt").write_text("old\n")
    calls = iter([[_FakeToolCall("c1", "read_file", '{"path": "a.txt"}')], []])
    monkeypatch.setattr(agent, "_stream_llm", _fake_stream_factory(calls))

    async def scenario():
        return [ev async for ev in agent.run_turn(
            "read it", [], None, "m", effort="Low", workspace_root=str(tmp_path),
            permission_mode="bypass", turn_id="t1")]

    events = asyncio.run(scenario())
    assert any(e.get("type") == "tool_error" and "blocked by my gate" in e.get("text", "")
               for e in events)


def test_pretooluse_hook_allow_cannot_override_gate_deny(monkeypatch, tmp_path):
    """A hook 'allow' must NOT resurrect a tool the rules gate already denied
    (plan mode denies write_file)."""
    from ocd_core.harness import hooks

    async def _fake_run(event, payload, cwd=None):
        return hooks.HookDecision(decision="allow")

    monkeypatch.setattr(hooks, "run", _fake_run)
    calls = iter([[_FakeToolCall("c1", "write_file", '{"path":"x.txt","content":"y"}')], []])
    monkeypatch.setattr(agent, "_stream_llm", _fake_stream_factory(calls))

    async def scenario():
        return [ev async for ev in agent.run_turn(
            "write it", [], None, "m", effort="Low", workspace_root=str(tmp_path),
            permission_mode="plan", turn_id="t1")]

    events = asyncio.run(scenario())
    assert not (tmp_path / "x.txt").exists()          # never ran
    assert any(e.get("type") == "tool_error" for e in events)


def test_userpromptsubmit_context_reaches_model(monkeypatch, tmp_path):
    from ocd_core.harness import hooks
    seen = {}

    async def _fake_run(event, payload, cwd=None):
        if event == "UserPromptSubmit":
            return hooks.HookDecision(context="REMEMBER-XYZ")
        return hooks.HookDecision()

    monkeypatch.setattr(hooks, "run", _fake_run)

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        seen["messages"] = messages
        yield {"type": "delta", "scope": "answer", "text": "ok"}
        yield {"__done__": {"content": "ok", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        return [ev async for ev in agent.run_turn("hi", [], None, "m", effort="Low",
                                                  turn_id="t1")]

    asyncio.run(scenario())
    assert any("REMEMBER-XYZ" in str(m.get("content", "")) for m in seen["messages"])


def test_userpromptsubmit_deny_ends_turn(monkeypatch, tmp_path):
    from ocd_core.harness import hooks

    async def _fake_run(event, payload, cwd=None):
        if event == "UserPromptSubmit":
            return hooks.HookDecision(decision="deny", reason="prompt refused")
        return hooks.HookDecision()

    monkeypatch.setattr(hooks, "run", _fake_run)

    async def _never(*a, **k):
        raise AssertionError("the model must not be called when the prompt is blocked")
        yield {}

    monkeypatch.setattr(agent, "_stream_llm", _never)

    async def scenario():
        return [ev async for ev in agent.run_turn("hi", [], None, "m", effort="Low",
                                                  turn_id="t1")]

    events = asyncio.run(scenario())
    assert any("prompt refused" in str(e.get("text", "")) for e in events)
```

- [ ] **Step 2: Run red**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_agent_workspace.py -k hook -q`
Expected: FAIL — hooks are never consulted (no deny appears; the model is called).

- [ ] **Step 3a: Wire `UserPromptSubmit`**

**First**, add the module import once at the top of `agent.py`'s existing `from . import (...)` block (`agent.py:78-96`) — alongside `config`, `permissions`, etc. — rather than importing inside `run_turn`:
```python
from .harness import hooks as _hooks
```
(Place it after the existing `from .llm import ...` lines, its own line, isort-clean. Task 6 reuses this same import — do NOT re-import inside the function.)

Then in `agent.py`, immediately **before** `messages = [{"role": "system", ...}]` (`agent.py:1349`), insert:
```python
    # Hooks (P2a): UserPromptSubmit may inject context or block the turn outright.
    _hk = await _hooks.run("UserPromptSubmit",
                           {"prompt": goal, "turn_id": turn_id or "",
                            "cwd": workspace_root or ""}, cwd=workspace_root)
    if _hk.denied:
        yield {"type": "error", "text": f"Blocked by hook: {_hk.reason}"}
        yield {"type": "done"}
        return
    if _hk.context:
        if isinstance(user_content, list):
            user_content = [{"type": "text",
                             "text": f"{_hk.context}\n\n{user_content[0]['text']}"},
                            *user_content[1:]]
        else:
            user_content = f"{_hk.context}\n\n{user_content}"
```

- [ ] **Step 3b: Wire `PreToolUse`**

In `agent.py`, immediately **before** the existing HITL gate line `if gate_on and not domain_gate_prompted and permissions.requires_approval(name, perm_mode, args):` (`agent.py:1757`), insert:
```python
            # Hooks (P2a): PreToolUse runs AFTER the rules gate (a gate deny already
            # `continue`d above, so a hook can never resurrect it) and BEFORE the HITL
            # prompt — it may deny outright, or force a prompt the mode would have skipped.
            # Reset per tool call: a previous iteration's values must never leak forward.
            _hook_forces_ask = False
            _hook_allows = False
            _hk = await _hooks.run("PreToolUse",
                                   {"tool_name": name, "tool_input": args,
                                    "turn_id": turn_id or "",
                                    "cwd": workspace_root or ""}, cwd=workspace_root)
            if _hk.denied:
                yield {"type": "tool_error", "id": tc.id, "name": name,
                       "text": f"Blocked by hook: {_hk.reason}"}
                blocked_outcomes.append({"id": tc.id, "name": name, "ok": False,
                    "skip_breaker": True,
                    "result": f"BLOCKED by a PreToolUse hook: {_hk.reason}"})
                continue
            _hook_forces_ask = _hk.decision == "ask"
            _hook_allows = _hk.decision == "allow"
```
Then change that same HITL gate condition to respect the hook — replace:
```python
            if gate_on and not domain_gate_prompted and permissions.requires_approval(name, perm_mode, args):
```
with:
```python
            if (gate_on and not domain_gate_prompted and not _hook_allows
                    and (_hook_forces_ask
                         or permissions.requires_approval(name, perm_mode, args))):
```

*Implementer note:* the workspace rule-gate block sits just above this line and `continue`s on its own `deny`/`allow`; leave it untouched. Verify by reading that a gate `deny` reaches `continue` **before** your `PreToolUse` insertion — that is what makes "a hook cannot loosen a gate deny" true by construction.

- [ ] **Step 4: Run green + regression**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_agent_workspace.py backend/tests/test_agent_hitl.py backend/tests/test_permissions.py backend/tests/test_harness_rules.py -q`
Expected: PASS — the 4 new hook tests plus every pre-existing test. Ruff clean on `agent.py`.

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/agent.py backend/tests/test_agent_workspace.py
git commit -m "feat(harness): wire PreToolUse + UserPromptSubmit hooks into run_turn"
```

---

## Task 6: Wire the three observational call sites (`SessionStart`, `PostToolUse`, `Stop`)

**Files:**
- Modify: `backend/ocd_core/agent.py` (~`:1304`, `:1813`, `:1886-1924`)
- Test: `backend/tests/test_agent_workspace.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_agent_workspace.py
def test_sessionstart_context_reaches_system_prompt(monkeypatch):
    from ocd_core.harness import hooks
    seen = {}

    async def _fake_run(event, payload, cwd=None):
        if event == "SessionStart":
            return hooks.HookDecision(context="SESSION-MARKER-42")
        return hooks.HookDecision()

    monkeypatch.setattr(hooks, "run", _fake_run)

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        seen["system"] = messages[0]["content"]
        yield {"type": "delta", "scope": "answer", "text": "ok"}
        yield {"__done__": {"content": "ok", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        return [ev async for ev in agent.run_turn("hi", [], None, "m", effort="Low",
                                                  turn_id="t1")]

    asyncio.run(scenario())
    assert "SESSION-MARKER-42" in seen["system"]


def test_posttooluse_hook_observes_without_changing_outcome(monkeypatch, tmp_path):
    from ocd_core.harness import hooks
    calls_seen = []

    async def _fake_run(event, payload, cwd=None):
        if event == "PostToolUse":
            calls_seen.append(payload.get("tool_name"))
        return hooks.HookDecision()

    monkeypatch.setattr(hooks, "run", _fake_run)
    (tmp_path / "a.txt").write_text("hello\n")
    calls = iter([[_FakeToolCall("c1", "read_file", '{"path": "a.txt"}')], []])
    monkeypatch.setattr(agent, "_stream_llm", _fake_stream_factory(calls))

    async def scenario():
        return [ev async for ev in agent.run_turn(
            "read it", [], None, "m", effort="Low", workspace_root=str(tmp_path),
            permission_mode="bypass", turn_id="t1")]

    events = asyncio.run(scenario())
    assert "read_file" in calls_seen
    assert any(e.get("type") == "tool_result" for e in events)      # outcome unchanged


def test_stop_hook_fires_once_at_end(monkeypatch):
    from ocd_core.harness import hooks
    fired = []

    async def _fake_run(event, payload, cwd=None):
        if event == "Stop":
            fired.append(event)
        return hooks.HookDecision()

    monkeypatch.setattr(hooks, "run", _fake_run)

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        yield {"type": "delta", "scope": "answer", "text": "ok"}
        yield {"__done__": {"content": "ok", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        return [ev async for ev in agent.run_turn("hi", [], None, "m", effort="Low",
                                                  turn_id="t1")]

    asyncio.run(scenario())
    assert fired == ["Stop"]
```

- [ ] **Step 2: Run red**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_agent_workspace.py -k "sessionstart or posttooluse or stop_hook" -q`
Expected: FAIL — the marker never reaches the prompt; `calls_seen`/`fired` stay empty.

- [ ] **Step 3a: Wire `SessionStart`**

In `agent.py`, right after `extra_sections = []` (`agent.py:1304`), insert (the `_hooks` import already exists at module level from Task 5 — do not re-import):
```python
    # Hooks (P2a): SessionStart may inject context into the system prompt.
    _hk_start = await _hooks.run("SessionStart",
                                 {"turn_id": turn_id or "", "cwd": workspace_root or ""},
                                 cwd=workspace_root)
    if _hk_start.context:
        extra_sections.append(_hk_start.context)
```

- [ ] **Step 3b: Wire `PostToolUse`**

In the drain loop, right after `for ev in _completion_events(out, streamed): yield ev` (`agent.py:1813`), insert:
```python
                        _hk_post = await _hooks.run(
                            "PostToolUse",
                            {"tool_name": out.get("name"), "tool_input": {},
                             "tool_response": str(out.get("result", ""))[:2000],
                             "turn_id": turn_id or "", "cwd": workspace_root or ""},
                            cwd=workspace_root)
                        if _hk_post.context:
                            messages.append({"role": "user",
                                             "content": _hk_post.context})
```

- [ ] **Step 3c: Wire `Stop`**

In `agent.py`, immediately before the turn's final `yield {"type": "done"}` (find it near the end of `run_turn`, after the verification pass at `agent.py:1920-1924`), insert:
```python
    _hk_stop = await _hooks.run("Stop", {"turn_id": turn_id or "",
                                         "cwd": workspace_root or ""},
                                cwd=workspace_root)
    if _hk_stop.context:
        yield {"type": "delta", "scope": "answer", "text": f"\n\n{_hk_stop.context}"}
```

- [ ] **Step 4: Run green + regression**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_agent_workspace.py backend/tests/test_agent_hitl.py backend/tests/test_permissions.py backend/tests/test_harness_hooks.py -q`
Expected: PASS. Ruff clean.

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/agent.py backend/tests/test_agent_workspace.py
git commit -m "feat(harness): wire SessionStart/PostToolUse/Stop hooks into run_turn"
```

---

## Task 7: Adversarial verify + docs + full gate

- [ ] **Step 1: Full backend gate**

Run: `.venv\Scripts\python.exe -m pytest backend/tests/test_harness_hooks.py backend/tests/test_agent_workspace.py backend/tests/test_agent_hitl.py backend/tests/test_permissions.py backend/tests/test_harness_rules.py backend/tests/test_bash_jail.py -q`
Expected: PASS except the documented `test_bash_jail::test_run_bash_still_allows_safe_relative` Windows-`echo` baseline. Then `.venv\Scripts\python.exe -m ruff check .` → clean.

- [ ] **Step 2: Adversarial verify (subagent)**

Dispatch a fresh subagent to try to break the hook layer, writing throwaway probes (not committed) against the real `hooks.run`:
- Can a hook **loosen** a decision? Configure a `PreToolUse` hook returning `allow` and drive a turn in `plan` mode against `write_file` (gate-denied) — the file must not be written.
- Does `PreToolUse` genuinely **fail closed**? Probe: a command that doesn't exist; one that exits 1; one that prints `{` (malformed); one that sleeps past its timeout. All four must deny.
- Can a hook read secrets? Set `OCD_API_TOKEN` and have a hook print `os.environ` — the value must be absent.
- Is the command line injectable from tool input? Configure a hook whose command is `python probe.py` and drive a tool call whose argument contains `"; malicious"` / `$(...)` / backticks — confirm the payload arrives as **stdin JSON** and never alters the argv.
- Can a **workspace** contribute a hook? Write a `.claude/settings.json` with a `hooks` block into an attached workspace and confirm it is ignored (this is the headline trust guarantee).
- Does a zero-hook config truly spawn nothing (assert no subprocess created)?
Any real escape → add a failing test and fix. Record the outcome ("hooks HOLD across N classes") in the commit body.

- [ ] **Step 3: Docs**

In `README.md`'s Harness section, add after the "Run in the folder" bullet:
```
- **Hooks** — run your own shell command at lifecycle events (`SessionStart`,
  `UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`): it receives the event as JSON
  on stdin and can inject context, block a prompt, or tighten a tool decision
  (`allow`/`deny`/`ask`). Hooks are configured in **app settings only** — never loaded
  from a workspace folder — and a `PreToolUse` hook that fails or times out **denies** the
  call rather than silently allowing it.
```
In `SECURITY.md`, after the workspace-bash clause added by P1.5, add:
```
  **Hooks** (harness): lifecycle hook commands come from the app's own settings only —
  a workspace/repo can never contribute one. Tool input reaches a hook as stdin JSON
  (never interpolated into its command line), hooks run with the same secret-stripped
  environment as workspace bash, and a failing/timing-out `PreToolUse` hook fails closed
  (denies the tool call). See `backend/tests/test_harness_hooks.py`.
```
In `docs/superpowers/specs/2026-07-20-harness-design.md`, update the P2 roadmap row to note hooks shipped (cite `2026-07-22-harness-hooks-design.md`), leaving P2b/P2c pending.

- [ ] **Step 4: Commit**

```bash
git add -A backend/ README.md SECURITY.md docs/superpowers/specs/2026-07-20-harness-design.md
git commit -m "test(harness): adversarial-verify hooks + docs (shipped)"
```

- [ ] **Step 5: Deliver**

Push `feat/harness-hooks` and open a PR against `main` linking the spec. Summarize in the PR body: the five events, the app-settings-only trust boundary, fail-closed `PreToolUse`, tighten-only composition with the P1 gate, and the adversarial-verify outcome.

---

## Self-Review Notes (for the executor)

- **Spec coverage:** §3 events → Tasks 5-6; §4 contract (JSON in/out, exit codes, config shape) → Tasks 1, 3, 4; §5 architecture/module API → Tasks 1-4; §6 safety (trust, fail-closed, tighten-only, bounded, audited) → Tasks 1, 3, 4, 5 + Task 7's adversarial pass; §7 failure matrix → Task 3's parse tests; §8 testing → every task + Task 7; §9 file structure → the File Structure section.
- **Ordering matters:** Task 5 (blocking wiring) lands before Task 6 (observational) so the security-critical path is proven before the cosmetic one, and the HITL regression suite runs at both steps.
- **The one subtle edit** is Task 5 Step 3b's rewrite of the HITL gate condition — `not _hook_allows and (_hook_forces_ask or permissions.requires_approval(...))`. Read the surrounding block before editing; `_hook_allows`/`_hook_forces_ask` must be defined on every path that reaches the condition (they are, because the hook call precedes it unconditionally).
- **Not in scope (do not add):** `http`/`prompt`/`agent` hook types, subagent/compaction events, workspace-supplied hooks or a trust flow, a desktop settings UI, streaming hook output into the transcript.
