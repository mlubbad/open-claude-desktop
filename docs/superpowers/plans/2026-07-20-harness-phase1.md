# Harness Phase 1 — Agentic Coding Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give an open-claude-desktop chat a workspace-scoped coding agent — a Windows-safe path jail, a five-tool file suite (`read_file`/`edit_file`/`write_file`/`glob`/`grep`), permission modes + allow/deny/ask rules layered on the existing HITL gate, per-turn file checkpoints with restore, a model-driven plan tool, and environment-context assembly — all wired into the existing `run_turn` loop and streamed to the desktop UI.

**Architecture:** A new `backend/ocd_core/harness/` package holds one module per concern (`workspace_fs`, `rules`, `checkpoints`, `plan_tool`, `env_context`) plus a `workspace_registry` store. `run_turn` gains a `workspace_root` parameter; when set, the five file tools + `task_plan` are registered and dispatched alongside the existing tools, and the existing permission gate consults `rules` before falling through to the current `permissions.registry.wait()` approval flow. No rewrite of the loop — additive integration at the tool-spec list, the dispatch table (`_run_one_tool`), and the gate (`agent.py:~1629`). The desktop adds a workspace bar, tool timeline, diff cards, plan card, and rewind menu over the existing SSE stream.

**Tech Stack:** Python 3.12, FastAPI, pytest (+ `pytest-asyncio`), the existing `jsonstore` atomic JSON registry, `ocd_core.config`/`observability`/`permissions`; desktop React + TypeScript + Vitest (Tauri shell).

**Base:** branch `feat/harness` in worktree `.claude/worktrees/harness-spec`, base = `origin/main` (`373580f`). Spec: `docs/superpowers/specs/2026-07-20-harness-design.md`.

**Baseline (measured 2026-07-20 on the worktree, before any harness code):** the checkout equals `origin/main` (`373580f`), which is green in CI (Linux + Postgres). Locally on **Windows without Postgres**, ~10 pre-existing tests fail/error for environment reasons unrelated to the harness — do NOT chase them:
- `test_cowork.py` (4 errors): `ModuleNotFoundError: asyncpg` / Postgres unreachable — no local DB.
- `test_workspace.py::test_read_file_returns_content`, `test_code_routes`: `"...\r\n" == "...\n"` — Windows autocrlf checkout writes CRLF; the Linux CI checkout is LF.
- `test_providers_route.py::test_set_and_delete_key`: Windows keyring backend.
- `test_bash_jail.py::test_run_bash_still_allows_safe_relative`, `test_integration_routes_extra` (MCP discovery timeout), `test_project_kb_tool`: environment/timing.

**Therefore:** run the harness test files directly while developing (`pytest backend/tests/test_harness_*.py backend/tests/test_agent_workspace.py -q`); treat "green" in Task 18/22 as **no NEW failures beyond this documented baseline**, and rely on CI (Linux + services) for the authoritative full-suite green. The harness tests in this plan use `tmp_path` + Python `read_text`/`write_text` throughout (which round-trips `\n` correctly even on Windows), so they are immune to the CRLF trap — but if you add a test that reads a git-checked-out fixture file, normalize newlines in the assertion.

**Conventions (read once):**
- `PY = ../../.venv/Scripts/python.exe` from inside `backend/` — i.e. run backend tests as `../.venv/Scripts/python.exe -m pytest tests/... -q` from the worktree's `backend/` dir, OR `pytest backend/tests` from repo root after `pip install -e ./backend[dev]` (the CI recipe). This plan uses the repo-root form.
- Tests import the installed package top-level as `ocd_core` / `app`, never `backend.ocd_core`.
- TDD per task: write the failing test → run red → implement minimal → run green → commit. Keep commits small.
- Tool specs are OpenAI-shape `{"type": "function", "function": {"name","description","parameters"}}` (see `agent.py:100`). Tool dispatch is a big `if name == …` ladder inside `_run_one_tool` (`agent.py:861`). The turn loop's gate is at `agent.py:~1629`.
- Existing jail helper `integrations._jail_path` (`integrations.py:2137`) is **string-prefix based and NOT symlink/junction-safe** — Phase 1 introduces a hardened replacement in `harness/workspace_fs.py`. Do not reuse `_jail_path` for the new tools.

---

## File Structure

**Create:**
- `backend/ocd_core/harness/__init__.py` — package marker + public re-exports.
- `backend/ocd_core/harness/workspace_fs.py` — path jail (`resolve_in_workspace`) + the five file-tool implementations + their tool specs.
- `backend/ocd_core/harness/rules.py` — permission modes, mode aliases, allow/deny/ask rule engine (pure functions), `.claude/settings.json` import.
- `backend/ocd_core/harness/checkpoints.py` — per-workspace content-addressed snapshot store, checkpoint open/list/restore.
- `backend/ocd_core/harness/plan_tool.py` — in-turn plan state + `task_plan` tool spec/handler.
- `backend/ocd_core/harness/env_context.py` — environment section builder for the system prompt.
- `backend/ocd_core/workspace_registry.py` — id→root registry (recents, rules, protected paths) on disk via `jsonstore`.
- `backend/app/routes/harness.py` — workspace CRUD/recents + checkpoint list/restore routes.
- Tests: `backend/tests/test_harness_jail.py`, `test_harness_fs_tools.py`, `test_harness_rules.py`, `test_harness_checkpoints.py`, `test_harness_plan_tool.py`, `test_harness_env_context.py`, `test_harness_registry.py`, `test_harness_routes.py`, `test_agent_workspace.py`.
- Desktop: `desktop/src/components/WorkspaceBar.tsx` (+ `.test.tsx`), `ToolTimeline.tsx` (+ test), `FileDiffCard.tsx` (+ test), `PlanCard.tsx` (+ test), `RewindMenu.tsx` (+ test).

**Modify:**
- `backend/ocd_core/agent.py` — register file tools + `task_plan` when `workspace_root` set; dispatch them in `_run_one_tool`; consult `rules` in the gate; append env context to the system prompt; emit `tool_call`/`file_diff`/`plan_update`/`checkpoint` events.
- `backend/app/schemas.py` — add `workspace_id` to `AgentTurnRequest`; extend `permission_mode` validator with the new modes/aliases.
- `backend/app/routes/agent.py` — resolve `workspace_id`→root, thread `workspace_root` into `run_turn`.
- `backend/app/main.py` — include the new `harness` router.
- `desktop/src/api/events.ts` — types for the new events.
- `desktop/src/components/Composer.tsx` / `Message.tsx` — mount workspace bar, timeline, diff/plan/rewind.

---

## Task 1: Harness package skeleton

**Files:**
- Create: `backend/ocd_core/harness/__init__.py`
- Test: `backend/tests/test_harness_jail.py` (import smoke only for now)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_harness_jail.py
def test_harness_package_imports():
    import ocd_core.harness as h
    assert h is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest backend/tests/test_harness_jail.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ocd_core.harness'`

- [ ] **Step 3: Create the package**

```python
# backend/ocd_core/harness/__init__.py
"""Harness — workspace-scoped agentic coding layer (path jail, file tools,
permission rules, checkpoints, plan tool, env context). See
docs/superpowers/specs/2026-07-20-harness-design.md."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest backend/tests/test_harness_jail.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/harness/__init__.py backend/tests/test_harness_jail.py
git commit -m "feat(harness): add harness package skeleton"
```

---

## Task 2: Path jail (`resolve_in_workspace`)

The jail is the security foundation; everything else depends on it. It must resolve symlinks/junctions and reject escapes, unlike the legacy string-prefix `_jail_path`.

**Files:**
- Create: `backend/ocd_core/harness/workspace_fs.py`
- Test: `backend/tests/test_harness_jail.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_harness_jail.py
import os
import pytest
from pathlib import Path
from ocd_core.harness import workspace_fs as wfs


def test_resolves_normal_child(tmp_path):
    (tmp_path / "src").mkdir()
    p = wfs.resolve_in_workspace(tmp_path, "src/app.py")
    assert isinstance(p, Path)
    assert p == (tmp_path / "src" / "app.py").resolve()


def test_rejects_parent_traversal(tmp_path):
    with pytest.raises(wfs.JailError):
        wfs.resolve_in_workspace(tmp_path, "../secret.txt")


def test_rejects_absolute_outside(tmp_path):
    with pytest.raises(wfs.JailError):
        wfs.resolve_in_workspace(tmp_path, "C:/Windows/system32/x" if os.name == "nt" else "/etc/passwd")


def test_rejects_sibling_prefix_root(tmp_path):
    # C:\ws must not match C:\ws2 — the classic string-prefix bug.
    root = tmp_path / "ws"
    root.mkdir()
    sibling = tmp_path / "ws2"
    sibling.mkdir()
    (sibling / "f.txt").write_text("x")
    with pytest.raises(wfs.JailError):
        wfs.resolve_in_workspace(root, "../ws2/f.txt")


def test_rejects_symlink_escape(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("s")
    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this host")
    with pytest.raises(wfs.JailError):
        wfs.resolve_in_workspace(root, "escape/secret.txt")


def test_empty_path_returns_root(tmp_path):
    assert wfs.resolve_in_workspace(tmp_path, "") == tmp_path.resolve()


def test_rejects_nonexistent_segment_then_parent_escape(tmp_path):
    # A non-existent leading segment followed by .. must not escape (POSIX realpath case:
    # `Path.resolve(strict=False)` collapses the .. before the relative_to check).
    with pytest.raises(wfs.JailError):
        wfs.resolve_in_workspace(tmp_path, "fakedir/../../outside/secret.txt")
```

- [ ] **Step 2: Run red**

Run: `pytest backend/tests/test_harness_jail.py -q`
Expected: FAIL — `AttributeError: module has no attribute 'resolve_in_workspace'` / `JailError`.

- [ ] **Step 3: Implement the jail**

```python
# backend/ocd_core/harness/workspace_fs.py
"""Workspace path jail + file-tool implementations.

The jail resolves the *real* path (symlinks/junctions followed) and requires it to
lie at or under the real workspace root. Unlike the legacy string-prefix jail in
integrations.py, this defeats symlink/junction escapes and sibling-prefix roots
(C:\\ws vs C:\\ws2). Pure and exhaustively unit-testable.
"""
from __future__ import annotations

from pathlib import Path


class JailError(Exception):
    """Raised when a user-supplied path escapes the workspace root."""


def resolve_in_workspace(root: Path, user_path: str) -> Path:
    """Resolve ``user_path`` (workspace-relative) to a real absolute path under ``root``.

    Raises ``JailError`` on any escape (parent traversal, absolute path outside,
    symlink/junction that points out, sibling-prefix root). An empty path resolves to
    the root itself. A leading-absolute path (``/etc/passwd``, ``C:/Windows``) is
    rejected — the model must use workspace-relative paths.
    """
    root_real = Path(root).resolve()
    raw = (user_path or "").strip().replace("\\", "/")
    if raw.startswith("workspace/"):   # strip an accidental workspace/ prefix the model adds
        raw = raw[len("workspace/"):]
    if raw in ("", "."):
        return root_real
    # resolve(strict=False): follows real symlinks/junctions, collapses .. (even through a
    # non-existent tail — the write_file/create case), so the relative_to check below cannot
    # be fooled by a literal .. left in the path. Do NOT hand-roll ancestor resolution: a
    # non-existent segment followed by .. (e.g. "fakedir/../../x") escaped that way on POSIX.
    real = (root_real / raw).resolve(strict=False)
    try:
        real.relative_to(root_real)
    except ValueError:
        raise JailError(f"path escapes workspace: {user_path!r}") from None
    return real
```

> **Review fix (2026-07-20):** the first draft used a custom `_resolve_existing_prefix`
> helper and `.lstrip("/")`. Code review found two POSIX-only escapes: (1) a non-existent
> segment + `..` left a literal `..` in the returned path that `relative_to` didn't catch
> (exploitable through `write_file`'s `mkdir(parents=True)`); (2) `.lstrip("/")` turned
> `/etc/passwd` into a contained path, failing `test_rejects_absolute_outside`. Both fixed
> by the code above (`resolve(strict=False)` + no slash-strip). CI is Linux, so verify there.

- [ ] **Step 4: Run green**

Run: `pytest backend/tests/test_harness_jail.py -q`
Expected: PASS — 8 tests (the symlink test may `skip` on hosts without symlink permission — acceptable). Also run `ruff check backend/ocd_core/harness backend/tests/test_harness_jail.py` → clean.

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/harness/workspace_fs.py backend/tests/test_harness_jail.py
git commit -m "feat(harness): symlink-safe workspace path jail"
```

---

## Task 3: `read_file` tool

**Files:**
- Modify: `backend/ocd_core/harness/workspace_fs.py`
- Test: `backend/tests/test_harness_fs_tools.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_harness_fs_tools.py
import pytest
from ocd_core.harness import workspace_fs as wfs


def test_read_file_numbers_lines(tmp_path):
    (tmp_path / "a.txt").write_text("first\nsecond\nthird\n")
    out = wfs.read_file(tmp_path, "a.txt")
    assert out["ok"] is True
    assert "1\tfirst" in out["content"]
    assert "3\tthird" in out["content"]


def test_read_file_offset_limit(tmp_path):
    (tmp_path / "a.txt").write_text("l1\nl2\nl3\nl4\nl5\n")
    out = wfs.read_file(tmp_path, "a.txt", offset=2, limit=2)
    assert "2\tl2" in out["content"] and "3\tl3" in out["content"]
    assert "l1" not in out["content"] and "l4" not in out["content"]


def test_read_file_missing(tmp_path):
    out = wfs.read_file(tmp_path, "nope.txt")
    assert out["ok"] is False and "not found" in out["error"].lower()


def test_read_file_outside_jail(tmp_path):
    out = wfs.read_file(tmp_path, "../x.txt")
    assert out["ok"] is False and "workspace" in out["error"].lower()
```

- [ ] **Step 2: Run red**

Run: `pytest backend/tests/test_harness_fs_tools.py -q`
Expected: FAIL — no `read_file`.

- [ ] **Step 3: Implement**

```python
# add to backend/ocd_core/harness/workspace_fs.py
from . import _errors  # noqa: F401  (placeholder if needed; else inline)

MAX_READ_LINES = 2000
MAX_LINE_CHARS = 2000


def _ok(**kw):
    return {"ok": True, **kw}


def _err(msg: str):
    return {"ok": False, "error": msg}


def read_file(root, user_path, offset: int = 1, limit: int = MAX_READ_LINES):
    """Read a text file, returning cat -n style numbered lines from ``offset`` (1-based)."""
    try:
        target = resolve_in_workspace(root, user_path)
    except JailError:
        return _err("path is outside the workspace")
    if not target.is_file():
        return _err(f"file not found: {user_path}")
    try:
        data = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return _err("file is not UTF-8 text")
    lines = data.splitlines()
    start = max(1, offset)
    chunk = lines[start - 1: start - 1 + max(1, limit)]
    numbered = []
    for i, line in enumerate(chunk, start=start):
        if len(line) > MAX_LINE_CHARS:
            line = line[:MAX_LINE_CHARS] + "…[truncated]"
        numbered.append(f"{i}\t{line}")
    return _ok(content="\n".join(numbered), path=target.name,
               total_lines=len(lines), shown=len(chunk))
```

(If the `from . import _errors` placeholder is unused, omit it — inline `_ok`/`_err` as shown.)

- [ ] **Step 4: Run green**

Run: `pytest backend/tests/test_harness_fs_tools.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/harness/workspace_fs.py backend/tests/test_harness_fs_tools.py
git commit -m "feat(harness): read_file tool (numbered, offset/limit, jailed)"
```

---

## Task 4: `write_file` tool (with read-before-overwrite tracking)

`edit_file`/`write_file` enforce Claude Code's "must read before modifying" guard. The read-set is per-turn state passed in by the caller (Task 10 wires it); here it's a plain set argument.

**Files:**
- Modify: `backend/ocd_core/harness/workspace_fs.py`
- Test: `backend/tests/test_harness_fs_tools.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_harness_fs_tools.py
def test_write_new_file_no_read_required(tmp_path):
    seen = set()
    out = wfs.write_file(tmp_path, "new.txt", "hello\n", read_paths=seen)
    assert out["ok"] is True
    assert (tmp_path / "new.txt").read_text() == "hello\n"


def test_overwrite_requires_prior_read(tmp_path):
    (tmp_path / "e.txt").write_text("old\n")
    seen = set()
    out = wfs.write_file(tmp_path, "e.txt", "new\n", read_paths=seen)
    assert out["ok"] is False and "read" in out["error"].lower()


def test_overwrite_after_read_succeeds(tmp_path):
    (tmp_path / "e.txt").write_text("old\n")
    seen = set()
    wfs.read_file(tmp_path, "e.txt")
    seen.add(wfs.canonical_key(tmp_path, "e.txt"))
    out = wfs.write_file(tmp_path, "e.txt", "new\n", read_paths=seen)
    assert out["ok"] is True and (tmp_path / "e.txt").read_text() == "new\n"


def test_write_creates_parent_dirs(tmp_path):
    out = wfs.write_file(tmp_path, "a/b/c.txt", "x\n", read_paths=set())
    assert out["ok"] is True and (tmp_path / "a" / "b" / "c.txt").is_file()
```

- [ ] **Step 2: Run red**

Run: `pytest backend/tests/test_harness_fs_tools.py -q`
Expected: FAIL — no `write_file` / `canonical_key`.

- [ ] **Step 3: Implement**

```python
# add to backend/ocd_core/harness/workspace_fs.py
def canonical_key(root, user_path) -> str:
    """A stable per-file identity for read-tracking (real path, posix, case-folded)."""
    target = resolve_in_workspace(root, user_path)
    return target.as_posix().casefold()


def write_file(root, user_path, content: str, read_paths: set):
    """Create or overwrite a file. Overwriting an existing file requires it to have been
    read this turn (its key present in ``read_paths``) — Claude Code's anti-clobber guard.
    On success the file's key is added to ``read_paths`` (a write implies you now know it)."""
    try:
        target = resolve_in_workspace(root, user_path)
        key = target.as_posix().casefold()
    except JailError:
        return _err("path is outside the workspace")
    if target.exists() and key not in read_paths:
        return _err("must read the file before overwriting it (call read_file first)")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    read_paths.add(key)
    return _ok(path=user_path, bytes=len(content.encode("utf-8")))
```

- [ ] **Step 4: Run green**

Run: `pytest backend/tests/test_harness_fs_tools.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/harness/workspace_fs.py backend/tests/test_harness_fs_tools.py
git commit -m "feat(harness): write_file with read-before-overwrite guard"
```

---

## Task 5: `edit_file` tool (unique old_string)

**Files:**
- Modify: `backend/ocd_core/harness/workspace_fs.py`
- Test: `backend/tests/test_harness_fs_tools.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_harness_fs_tools.py
def _seen(root, rel):
    return {wfs.canonical_key(root, rel)}


def test_edit_replaces_unique_string(tmp_path):
    (tmp_path / "e.py").write_text("a = 1\nb = 2\n")
    out = wfs.edit_file(tmp_path, "e.py", "b = 2", "b = 3", read_paths=_seen(tmp_path, "e.py"))
    assert out["ok"] is True
    assert (tmp_path / "e.py").read_text() == "a = 1\nb = 3\n"


def test_edit_fails_when_old_string_not_unique(tmp_path):
    (tmp_path / "e.py").write_text("x = 1\nx = 1\n")
    out = wfs.edit_file(tmp_path, "e.py", "x = 1", "x = 2", read_paths=_seen(tmp_path, "e.py"))
    assert out["ok"] is False and "unique" in out["error"].lower()
    assert (tmp_path / "e.py").read_text() == "x = 1\nx = 1\n"  # unchanged


def test_edit_replace_all(tmp_path):
    (tmp_path / "e.py").write_text("x = 1\nx = 1\n")
    out = wfs.edit_file(tmp_path, "e.py", "x = 1", "x = 2", replace_all=True,
                        read_paths=_seen(tmp_path, "e.py"))
    assert out["ok"] is True and (tmp_path / "e.py").read_text() == "x = 2\nx = 2\n"


def test_edit_fails_when_old_string_absent(tmp_path):
    (tmp_path / "e.py").write_text("a = 1\n")
    out = wfs.edit_file(tmp_path, "e.py", "zzz", "yyy", read_paths=_seen(tmp_path, "e.py"))
    assert out["ok"] is False and "not found" in out["error"].lower()


def test_edit_requires_prior_read(tmp_path):
    (tmp_path / "e.py").write_text("a = 1\n")
    out = wfs.edit_file(tmp_path, "e.py", "a = 1", "a = 2", read_paths=set())
    assert out["ok"] is False and "read" in out["error"].lower()


def test_edit_returns_unified_diff(tmp_path):
    (tmp_path / "e.py").write_text("a = 1\n")
    out = wfs.edit_file(tmp_path, "e.py", "a = 1", "a = 2", read_paths=_seen(tmp_path, "e.py"))
    assert "-a = 1" in out["diff"] and "+a = 2" in out["diff"]
```

- [ ] **Step 2: Run red**

Run: `pytest backend/tests/test_harness_fs_tools.py -q`
Expected: FAIL — no `edit_file`.

- [ ] **Step 3: Implement**

```python
# add to backend/ocd_core/harness/workspace_fs.py
import difflib


def edit_file(root, user_path, old_string: str, new_string: str,
              replace_all: bool = False, read_paths: set | None = None):
    """Replace ``old_string`` with ``new_string`` in a file. Fails unless the file was
    read this turn, and (unless ``replace_all``) unless ``old_string`` occurs exactly once.
    Returns a unified diff on success."""
    read_paths = read_paths if read_paths is not None else set()
    try:
        target = resolve_in_workspace(root, user_path)
        key = target.as_posix().casefold()
    except JailError:
        return _err("path is outside the workspace")
    if not target.is_file():
        return _err(f"file not found: {user_path}")
    if key not in read_paths:
        return _err("must read the file before editing it (call read_file first)")
    before = target.read_text(encoding="utf-8")
    count = before.count(old_string)
    if count == 0:
        return _err(f"old_string not found in {user_path}")
    if count > 1 and not replace_all:
        return _err(f"old_string is not unique ({count} matches); add context or set replace_all")
    after = (before.replace(old_string, new_string) if replace_all
             else before.replace(old_string, new_string, 1))
    target.write_text(after, encoding="utf-8")
    diff = "\n".join(difflib.unified_diff(
        before.splitlines(), after.splitlines(),
        fromfile=user_path, tofile=user_path, lineterm=""))
    return _ok(path=user_path, replacements=(count if replace_all else 1), diff=diff)
```

- [ ] **Step 4: Run green**

Run: `pytest backend/tests/test_harness_fs_tools.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/harness/workspace_fs.py backend/tests/test_harness_fs_tools.py
git commit -m "feat(harness): edit_file with unique-old_string guard + diff"
```

---

## Task 6: `glob` and `grep` tools

**Files:**
- Modify: `backend/ocd_core/harness/workspace_fs.py`
- Test: `backend/tests/test_harness_fs_tools.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_harness_fs_tools.py
def test_glob_matches_pattern(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x")
    (tmp_path / "src" / "b.py").write_text("x")
    (tmp_path / "readme.md").write_text("x")
    out = wfs.glob(tmp_path, "**/*.py")
    assert out["ok"] is True
    assert set(out["paths"]) == {"src/a.py", "src/b.py"}


def test_glob_caps_results(tmp_path):
    for i in range(10):
        (tmp_path / f"f{i}.txt").write_text("x")
    out = wfs.glob(tmp_path, "*.txt", max_results=5)
    assert len(out["paths"]) == 5 and out["truncated"] is True


def test_grep_finds_lines(tmp_path):
    (tmp_path / "a.py").write_text("import os\nx = 1\nimport sys\n")
    out = wfs.grep(tmp_path, r"^import ")
    assert out["ok"] is True
    assert any("import os" in m for m in out["matches"])
    assert any("import sys" in m for m in out["matches"])
    assert not any("x = 1" in m for m in out["matches"])


def test_grep_files_mode(tmp_path):
    (tmp_path / "a.py").write_text("TODO fix\n")
    (tmp_path / "b.py").write_text("clean\n")
    out = wfs.grep(tmp_path, "TODO", mode="files")
    assert out["files"] == ["a.py"]


def test_grep_outside_jail(tmp_path):
    out = wfs.grep(tmp_path, "x", path="../")
    assert out["ok"] is False
```

- [ ] **Step 2: Run red**

Run: `pytest backend/tests/test_harness_fs_tools.py -q`
Expected: FAIL — no `glob`/`grep`.

- [ ] **Step 3: Implement**

```python
# add to backend/ocd_core/harness/workspace_fs.py
import re

_IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
                ".mypy_cache", ".pytest_cache", ".ruff_cache", "dist", "build",
                ".next", "target"}
MAX_GLOB = 500
MAX_GREP_MATCHES = 300


def _iter_files(root):
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in _IGNORE_DIRS for part in rel.parts):
            continue
        if p.is_file():
            yield p, rel


def glob(root, pattern: str, max_results: int = MAX_GLOB):
    root_real = resolve_in_workspace(root, "")
    hits = []
    for p in sorted(root_real.glob(pattern), key=lambda x: (x.is_dir(), x.name)):
        rel = p.relative_to(root_real)
        if any(part in _IGNORE_DIRS for part in rel.parts):
            continue
        hits.append(rel.as_posix())
    truncated = len(hits) > max_results
    return _ok(paths=hits[:max_results], truncated=truncated)


def grep(root, pattern: str, path: str = "", mode: str = "content",
         max_matches: int = MAX_GREP_MATCHES):
    try:
        base = resolve_in_workspace(root, path)
    except JailError:
        return _err("path is outside the workspace")
    try:
        rx = re.compile(pattern)
    except re.error as e:
        return _err(f"bad regex: {e}")
    root_real = resolve_in_workspace(root, "")
    scan_root = base if base.is_dir() else base.parent
    matches, files = [], []
    for p, rel in _iter_files(scan_root):
        try:
            text = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        relp = p.relative_to(root_real).as_posix()
        found = False
        for ln, line in enumerate(text.splitlines(), start=1):
            if rx.search(line):
                found = True
                if mode == "content" and len(matches) < max_matches:
                    matches.append(f"{relp}:{ln}:{line.strip()[:300]}")
        if found:
            files.append(relp)
    if mode == "files":
        return _ok(files=files[:max_matches], count=len(files))
    if mode == "count":
        return _ok(count=len(matches))
    return _ok(matches=matches, truncated=len(matches) >= max_matches)
```

- [ ] **Step 4: Run green**

Run: `pytest backend/tests/test_harness_fs_tools.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/harness/workspace_fs.py backend/tests/test_harness_fs_tools.py
git commit -m "feat(harness): glob + grep tools (jailed, bounded)"
```

---

## Task 7: File-tool specs + dispatch helper

Give the harness a single place that lists the OpenAI-shape tool specs and a dispatcher `run_fs_tool(name, args, root, read_paths)` the agent loop can call.

**Files:**
- Modify: `backend/ocd_core/harness/workspace_fs.py`
- Test: `backend/tests/test_harness_fs_tools.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_harness_fs_tools.py
def test_tool_specs_have_expected_names():
    names = {s["function"]["name"] for s in wfs.FILE_TOOL_SPECS}
    assert names == {"read_file", "edit_file", "write_file", "glob", "grep"}


def test_run_fs_tool_dispatches_read(tmp_path):
    (tmp_path / "a.txt").write_text("hi\n")
    seen = set()
    out = wfs.run_fs_tool("read_file", {"path": "a.txt"}, tmp_path, seen)
    assert out["ok"] is True and "1\thi" in out["content"]
    # reading records the path for later edit/write
    assert wfs.canonical_key(tmp_path, "a.txt") in seen


def test_run_fs_tool_unknown(tmp_path):
    out = wfs.run_fs_tool("nope", {}, tmp_path, set())
    assert out["ok"] is False
```

- [ ] **Step 2: Run red**

Run: `pytest backend/tests/test_harness_fs_tools.py -q`
Expected: FAIL — no `FILE_TOOL_SPECS`/`run_fs_tool`.

- [ ] **Step 3: Implement**

```python
# add to backend/ocd_core/harness/workspace_fs.py
FILE_TOOL_SPECS = [
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read a text file from the workspace. Returns cat -n style "
                       "line-numbered content. Always read a file before editing or "
                       "overwriting it.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path."},
            "offset": {"type": "integer", "description": "1-based first line (default 1)."},
            "limit": {"type": "integer", "description": "Max lines to return (default 2000)."}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "edit_file",
        "description": "Replace an EXACT unique snippet in a file. old_string must occur "
                       "exactly once unless replace_all is true. Read the file first.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string", "description": "Exact text to replace (unique)."},
            "new_string": {"type": "string", "description": "Replacement text."},
            "replace_all": {"type": "boolean", "description": "Replace every occurrence."}},
            "required": ["path", "old_string", "new_string"]}}},
    {"type": "function", "function": {
        "name": "write_file",
        "description": "Create a new file or overwrite an existing one. Overwriting "
                       "requires reading the file first.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"},
            "content": {"type": "string"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "glob",
        "description": "List workspace files matching a glob pattern (e.g. **/*.py).",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"}},
            "required": ["pattern"]}}},
    {"type": "function", "function": {
        "name": "grep",
        "description": "Search workspace file contents with a regular expression. "
                       "mode=content|files|count.",
        "parameters": {"type": "object", "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string", "description": "Optional sub-path to scope the search."},
            "mode": {"type": "string", "enum": ["content", "files", "count"]}},
            "required": ["pattern"]}}},
]


def run_fs_tool(name: str, args: dict, root, read_paths: set) -> dict:
    """Dispatch a file tool by name. Records read paths so edit/write can enforce the
    read-before-modify guard."""
    a = args or {}
    if name == "read_file":
        out = read_file(root, a.get("path", ""), int(a.get("offset", 1) or 1),
                        int(a.get("limit", MAX_READ_LINES) or MAX_READ_LINES))
        if out.get("ok"):
            try:
                read_paths.add(canonical_key(root, a.get("path", "")))
            except JailError:
                pass
        return out
    if name == "edit_file":
        return edit_file(root, a.get("path", ""), a.get("old_string", ""),
                         a.get("new_string", ""), bool(a.get("replace_all")), read_paths)
    if name == "write_file":
        return write_file(root, a.get("path", ""), a.get("content", ""), read_paths)
    if name == "glob":
        return glob(root, a.get("pattern", "*"))
    if name == "grep":
        return grep(root, a.get("pattern", ""), a.get("path", ""), a.get("mode", "content"))
    return _err(f"unknown file tool: {name}")


FILE_TOOL_NAMES = {"read_file", "edit_file", "write_file", "glob", "grep"}
```

- [ ] **Step 4: Run green**

Run: `pytest backend/tests/test_harness_fs_tools.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/harness/workspace_fs.py backend/tests/test_harness_fs_tools.py
git commit -m "feat(harness): file-tool specs + run_fs_tool dispatcher"
```

---

## Task 8: Permission modes + rule engine

**Files:**
- Create: `backend/ocd_core/harness/rules.py`
- Test: `backend/tests/test_harness_rules.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_harness_rules.py
from ocd_core.harness import rules


def test_mode_aliases():
    assert rules.normalize_mode("auto") == "bypass"
    assert rules.normalize_mode("ask") == "default"
    assert rules.normalize_mode("acceptEdits") == "acceptEdits"
    assert rules.normalize_mode("nonsense") == "strict"  # unknown fails closed


def test_deny_beats_allow():
    rs = rules.RuleSet(allow=["bash(*)"], deny=["bash(rm *)"])
    assert rs.decision("bash", {"command": "rm -rf x"}) == "deny"
    assert rs.decision("bash", {"command": "ls"}) == "allow"


def test_ask_rule():
    rs = rules.RuleSet(ask=["web_fetch"])
    assert rs.decision("web_fetch", {"url": "http://x"}) == "ask"


def test_matcher_glob_on_bash_command():
    rs = rules.RuleSet(allow=["bash(git *)"])
    assert rs.decision("bash", {"command": "git status"}) == "allow"
    assert rs.decision("bash", {"command": "npm i"}) is None  # no rule matched


def test_bare_tool_matches_all_invocations():
    rs = rules.RuleSet(allow=["read_file"])
    assert rs.decision("read_file", {"path": "a"}) == "allow"


def test_gate_default_mode_edit_prompts_without_rule():
    # In default mode a file edit with no matching rule -> prompt (ask).
    assert rules.gate("edit_file", {"path": "a"}, "default", rules.RuleSet()) == "ask"


def test_gate_accept_edits_auto_approves_file_edit():
    assert rules.gate("edit_file", {"path": "a"}, "acceptEdits", rules.RuleSet()) == "allow"


def test_gate_plan_mode_blocks_write():
    assert rules.gate("write_file", {"path": "a"}, "plan", rules.RuleSet()) == "deny"


def test_gate_plan_mode_allows_read():
    assert rules.gate("read_file", {"path": "a"}, "plan", rules.RuleSet()) == "allow"


def test_gate_bypass_allows_everything():
    assert rules.gate("bash", {"command": "rm -rf /"}, "bypass", rules.RuleSet()) == "allow"


def test_gate_rule_overrides_mode():
    rs = rules.RuleSet(deny=["bash(rm *)"])
    assert rules.gate("bash", {"command": "rm x"}, "bypass", rs) == "deny"
```

- [ ] **Step 2: Run red**

Run: `pytest backend/tests/test_harness_rules.py -q`
Expected: FAIL — no `rules` module.

- [ ] **Step 3: Implement**

```python
# backend/ocd_core/harness/rules.py
"""Permission modes + allow/deny/ask rule engine (pure functions).

Modes: default | acceptEdits | plan | strict | bypass (legacy aliases auto->bypass,
ask->default). Rule precedence: deny > ask > allow > mode default.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field

READ_ONLY_TOOLS = {"read_file", "glob", "grep"}
WRITE_TOOLS = {"edit_file", "write_file"}

_ALIASES = {"auto": "bypass", "ask": "default"}
_MODES = {"default", "acceptEdits", "plan", "strict", "bypass"}
# Bash commands auto-approved in acceptEdits (jailed cwd already constrains them).
SAFE_BASH = {"ls", "cat", "head", "tail", "wc", "echo", "pwd", "grep", "find",
             "sort", "uniq", "cut", "mkdir", "touch", "mv", "cp", "sed", "git"}


def normalize_mode(mode: str | None) -> str:
    m = (mode or "default").strip()
    m = _ALIASES.get(m, m)
    return m if m in _MODES else "strict"  # unknown fails closed


def _parse(rule: str) -> tuple[str, str | None]:
    """'bash(git *)' -> ('bash', 'git *'); 'read_file' -> ('read_file', None)."""
    rule = rule.strip()
    if rule.endswith(")") and "(" in rule:
        name, matcher = rule[:-1].split("(", 1)
        return name.strip(), matcher.strip()
    return rule, None


def _arg_string(tool: str, args: dict) -> str:
    if tool == "bash":
        return str((args or {}).get("command", ""))
    return str((args or {}).get("path", "") or (args or {}).get("url", ""))


def _matches(rule: str, tool: str, args: dict) -> bool:
    name, matcher = _parse(rule)
    if name not in ("*", tool):
        return False
    if matcher is None or matcher == "*":
        return True
    return fnmatch.fnmatch(_arg_string(tool, args), matcher)


@dataclass
class RuleSet:
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    ask: list[str] = field(default_factory=list)

    def decision(self, tool: str, args: dict) -> str | None:
        """deny > ask > allow; None if no rule matches."""
        if any(_matches(r, tool, args) for r in self.deny):
            return "deny"
        if any(_matches(r, tool, args) for r in self.ask):
            return "ask"
        if any(_matches(r, tool, args) for r in self.allow):
            return "allow"
        return None


def gate(tool: str, args: dict, mode: str, ruleset: RuleSet) -> str:
    """Return 'allow' | 'deny' | 'ask' for a tool call. Rules win over mode defaults."""
    mode = normalize_mode(mode)
    ruled = ruleset.decision(tool, args)
    if ruled is not None:
        return ruled
    if mode == "bypass":
        return "allow"
    if mode == "plan":
        return "allow" if tool in READ_ONLY_TOOLS else "deny"
    if mode == "strict":
        return "ask"
    # default / acceptEdits
    if tool in READ_ONLY_TOOLS:
        return "allow"
    if tool in WRITE_TOOLS:
        return "allow" if mode == "acceptEdits" else "ask"
    if tool == "bash":
        head = str((args or {}).get("command", "")).strip().split(" ", 1)[0]
        if mode == "acceptEdits" and head in SAFE_BASH:
            return "allow"
        return "ask"
    return "ask"  # unknown/sensitive tool
```

- [ ] **Step 4: Run green**

Run: `pytest backend/tests/test_harness_rules.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/harness/rules.py backend/tests/test_harness_rules.py
git commit -m "feat(harness): permission modes + allow/deny/ask rule engine"
```

---

## Task 9: `.claude/settings.json` permission import

**Files:**
- Modify: `backend/ocd_core/harness/rules.py`
- Test: `backend/tests/test_harness_rules.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_harness_rules.py
import json


def test_load_claude_rules(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text(json.dumps({
        "permissions": {"allow": ["Bash(git *)", "Read"], "deny": ["Bash(rm *)"]}
    }))
    rs = rules.load_claude_ruleset(tmp_path)
    # Claude tool names map to ours; bare Read -> read_file
    assert rules.gate("bash", {"command": "git status"}, "default", rs) == "allow"
    assert rules.gate("bash", {"command": "rm x"}, "bypass", rs) == "deny"


def test_load_claude_rules_absent(tmp_path):
    rs = rules.load_claude_ruleset(tmp_path)
    assert rs.allow == [] and rs.deny == [] and rs.ask == []


def test_load_claude_rules_malformed(tmp_path):
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.json").write_text("{not json")
    rs = rules.load_claude_ruleset(tmp_path)  # must not raise
    assert isinstance(rs, rules.RuleSet)
```

- [ ] **Step 2: Run red**

Run: `pytest backend/tests/test_harness_rules.py -q`
Expected: FAIL — no `load_claude_ruleset`.

- [ ] **Step 3: Implement**

```python
# add to backend/ocd_core/harness/rules.py
from pathlib import Path

from .. import jsonstore

# Map Claude Code tool names to ours (best-effort; unmapped names pass through lowercased).
_CLAUDE_TOOL_MAP = {
    "Bash": "bash", "Read": "read_file", "Edit": "edit_file",
    "Write": "write_file", "Glob": "glob", "Grep": "grep", "WebFetch": "web_fetch",
}


def _map_rule(rule: str) -> str:
    name, matcher = _parse(rule)
    mapped = _CLAUDE_TOOL_MAP.get(name, name[:1].lower() + name[1:] if name else name)
    return f"{mapped}({matcher})" if matcher is not None else mapped


def load_claude_ruleset(workspace_root) -> RuleSet:
    """Read a workspace's .claude/settings.json permissions block into a RuleSet.
    Best-effort: any error yields an empty RuleSet (never raises)."""
    path = Path(workspace_root) / ".claude" / "settings.json"
    data = jsonstore.load_json(path, {})
    perms = data.get("permissions", {}) if isinstance(data, dict) else {}
    def conv(key):
        vals = perms.get(key, []) if isinstance(perms, dict) else []
        return [_map_rule(str(r)) for r in vals] if isinstance(vals, list) else []
    return RuleSet(allow=conv("allow"), deny=conv("deny"), ask=conv("ask"))
```

- [ ] **Step 4: Run green**

Run: `pytest backend/tests/test_harness_rules.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/harness/rules.py backend/tests/test_harness_rules.py
git commit -m "feat(harness): import .claude/settings.json permission rules"
```

---

## Task 10: Checkpoint store

**Files:**
- Create: `backend/ocd_core/harness/checkpoints.py`
- Test: `backend/tests/test_harness_checkpoints.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_harness_checkpoints.py
from ocd_core.harness import checkpoints


def test_snapshot_and_restore_file(tmp_path, monkeypatch):
    store = tmp_path / "ckpt"
    ws = tmp_path / "ws"; ws.mkdir()
    (ws / "a.txt").write_text("original\n")
    cp = checkpoints.CheckpointStore(store)

    cp.snapshot_before_edit("turn1", ws, "a.txt")   # capture original
    (ws / "a.txt").write_text("modified\n")          # simulate an edit

    assert cp.list("turn1")[0]["files"] == ["a.txt"]
    cp.restore("turn1", ws, what="files")
    assert (ws / "a.txt").read_text() == "original\n"


def test_snapshot_only_once_per_file_per_turn(tmp_path):
    ws = tmp_path / "ws"; ws.mkdir()
    (ws / "a.txt").write_text("v1\n")
    cp = checkpoints.CheckpointStore(tmp_path / "ckpt")
    cp.snapshot_before_edit("t", ws, "a.txt")
    (ws / "a.txt").write_text("v2\n")
    cp.snapshot_before_edit("t", ws, "a.txt")   # must NOT overwrite the v1 snapshot
    cp.restore("t", ws, what="files")
    assert (ws / "a.txt").read_text() == "v1\n"


def test_restore_new_file_deletes_it(tmp_path):
    # A file that did not exist at snapshot time is removed on restore.
    ws = tmp_path / "ws"; ws.mkdir()
    cp = checkpoints.CheckpointStore(tmp_path / "ckpt")
    cp.snapshot_before_edit("t", ws, "new.txt")   # file absent -> tombstone
    (ws / "new.txt").write_text("created\n")
    cp.restore("t", ws, what="files")
    assert not (ws / "new.txt").exists()


def test_list_empty_turn(tmp_path):
    cp = checkpoints.CheckpointStore(tmp_path / "ckpt")
    assert cp.list("unknown") == []
```

- [ ] **Step 2: Run red**

Run: `pytest backend/tests/test_harness_checkpoints.py -q`
Expected: FAIL — no `checkpoints` module.

- [ ] **Step 3: Implement**

```python
# backend/ocd_core/harness/checkpoints.py
"""Per-workspace file checkpoints for rewind.

Before a turn's FIRST modification of each file, its bytes (or a tombstone for a
not-yet-existing file) are snapshotted under a checkpoint keyed by turn id. Restore
writes snapshots back (or deletes tombstoned new files). Content is stored as plain
files under the app data dir. Bash-side mutations are NOT tracked (documented limit).
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .workspace_fs import resolve_in_workspace, JailError

MAX_CHECKPOINTS = 100


class CheckpointStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _dir(self, checkpoint_id: str) -> Path:
        d = self.root / checkpoint_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _manifest_path(self, checkpoint_id: str) -> Path:
        return self._dir(checkpoint_id) / "manifest.json"

    def _manifest(self, checkpoint_id: str) -> dict:
        p = self._manifest_path(checkpoint_id)
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"files": {}}

    def snapshot_before_edit(self, checkpoint_id: str, workspace_root, rel_path: str) -> None:
        try:
            target = resolve_in_workspace(workspace_root, rel_path)
        except JailError:
            return
        rel = target.relative_to(Path(workspace_root).resolve()).as_posix()
        man = self._manifest(checkpoint_id)
        if rel in man["files"]:
            return  # already snapshotted this turn — keep the earliest state
        d = self._dir(checkpoint_id)
        if target.is_file():
            blob = d / (str(len(man["files"])) + ".blob")
            shutil.copyfile(target, blob)
            man["files"][rel] = {"blob": blob.name, "existed": True}
        else:
            man["files"][rel] = {"blob": None, "existed": False}
        self._manifest_path(checkpoint_id).write_text(json.dumps(man), encoding="utf-8")

    def list(self, checkpoint_id: str) -> list[dict]:
        man = self._manifest(checkpoint_id)
        if not man.get("files"):
            return []
        return [{"checkpoint_id": checkpoint_id, "files": sorted(man["files"].keys())}]

    def restore(self, checkpoint_id: str, workspace_root, what: str = "files") -> int:
        if what not in ("files", "both"):
            return 0
        man = self._manifest(checkpoint_id)
        d = self._dir(checkpoint_id)
        restored = 0
        for rel, meta in man.get("files", {}).items():
            try:
                target = resolve_in_workspace(workspace_root, rel)
            except JailError:
                continue
            if meta.get("existed"):
                shutil.copyfile(d / meta["blob"], target)
            elif target.exists():
                target.unlink()
            restored += 1
        return restored
```

- [ ] **Step 4: Run green**

Run: `pytest backend/tests/test_harness_checkpoints.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/harness/checkpoints.py backend/tests/test_harness_checkpoints.py
git commit -m "feat(harness): per-turn file checkpoint store with restore"
```

---

## Task 11: Plan tool

**Files:**
- Create: `backend/ocd_core/harness/plan_tool.py`
- Test: `backend/tests/test_harness_plan_tool.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_harness_plan_tool.py
from ocd_core.harness import plan_tool


def test_set_plan_creates_items():
    plan = plan_tool.Plan()
    out = plan.apply({"op": "set", "items": [
        {"subject": "read code"}, {"subject": "write test"}]})
    assert out["ok"] is True
    assert [i["status"] for i in plan.snapshot()] == ["pending", "pending"]
    assert plan.snapshot()[0]["id"] == 1


def test_update_status():
    plan = plan_tool.Plan()
    plan.apply({"op": "set", "items": [{"subject": "a"}, {"subject": "b"}]})
    plan.apply({"op": "update", "id": 1, "status": "completed"})
    assert plan.snapshot()[0]["status"] == "completed"


def test_update_bad_status_rejected():
    plan = plan_tool.Plan()
    plan.apply({"op": "set", "items": [{"subject": "a"}]})
    out = plan.apply({"op": "update", "id": 1, "status": "banana"})
    assert out["ok"] is False


def test_tool_spec_name():
    assert plan_tool.PLAN_TOOL_SPEC["function"]["name"] == "task_plan"
```

- [ ] **Step 2: Run red**

Run: `pytest backend/tests/test_harness_plan_tool.py -q`
Expected: FAIL — no `plan_tool`.

- [ ] **Step 3: Implement**

```python
# backend/ocd_core/harness/plan_tool.py
"""Model-driven task plan for a workspace turn. One Plan per turn; the agent calls the
`task_plan` tool to set the item list and update item statuses. The loop emits the
snapshot as `plan_update` events for the UI plan card."""
from __future__ import annotations

_STATUSES = {"pending", "in_progress", "completed"}


class Plan:
    def __init__(self):
        self._items: list[dict] = []

    def apply(self, args: dict) -> dict:
        op = (args or {}).get("op")
        if op == "set":
            items = args.get("items") or []
            self._items = [
                {"id": i + 1, "subject": str(it.get("subject", "")).strip(),
                 "status": it.get("status", "pending") if it.get("status") in _STATUSES else "pending"}
                for i, it in enumerate(items)]
            return {"ok": True, "count": len(self._items)}
        if op == "update":
            iid = args.get("id")
            status = args.get("status")
            if status not in _STATUSES:
                return {"ok": False, "error": f"bad status: {status}"}
            for it in self._items:
                if it["id"] == iid:
                    it["status"] = status
                    return {"ok": True}
            return {"ok": False, "error": f"no item {iid}"}
        return {"ok": False, "error": f"unknown op: {op}"}

    def snapshot(self) -> list[dict]:
        return [dict(it) for it in self._items]


PLAN_TOOL_SPEC = {"type": "function", "function": {
    "name": "task_plan",
    "description": "Maintain a short task plan for multi-step work. op=set replaces the "
                   "item list ([{subject}]); op=update sets one item's status "
                   "(pending|in_progress|completed). Keep it to 3-8 concrete steps and "
                   "update statuses as you go so the user can follow along.",
    "parameters": {"type": "object", "properties": {
        "op": {"type": "string", "enum": ["set", "update"]},
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "subject": {"type": "string"}}}},
        "id": {"type": "integer"},
        "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}},
        "required": ["op"]}}}
```

- [ ] **Step 4: Run green**

Run: `pytest backend/tests/test_harness_plan_tool.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/harness/plan_tool.py backend/tests/test_harness_plan_tool.py
git commit -m "feat(harness): model-driven task_plan tool"
```

---

## Task 12: Environment context builder

**Files:**
- Create: `backend/ocd_core/harness/env_context.py`
- Test: `backend/tests/test_harness_env_context.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_harness_env_context.py
from ocd_core.harness import env_context


def test_build_includes_root_and_platform(tmp_path):
    (tmp_path / "app.py").write_text("x")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "m.py").write_text("y")
    text = env_context.build(tmp_path)
    assert str(tmp_path) in text
    assert "app.py" in text
    assert "src/" in text or "src" in text


def test_build_caps_file_map(tmp_path):
    for i in range(300):
        (tmp_path / f"f{i}.txt").write_text("x")
    text = env_context.build(tmp_path, max_entries=50)
    # never dumps more than the cap (+ a truncation note)
    assert text.count("\n- ") <= 51


def test_build_no_git_is_safe(tmp_path):
    # No .git dir -> no crash, no git section.
    text = env_context.build(tmp_path)
    assert isinstance(text, str) and "WORKSPACE" in text
```

- [ ] **Step 2: Run red**

Run: `pytest backend/tests/test_harness_env_context.py -q`
Expected: FAIL — no `env_context`.

- [ ] **Step 3: Implement**

```python
# backend/ocd_core/harness/env_context.py
"""Environment section appended to the system prompt for workspace turns: platform,
workspace root, git state, and a bounded file map. Deterministic and git-optional
(never fails the turn if git is missing)."""
from __future__ import annotations

import platform
import subprocess
from pathlib import Path

_IGNORE = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
           ".next", "target", ".mypy_cache", ".pytest_cache", ".ruff_cache"}


def _git(root: Path, *args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=root, capture_output=True,
                             text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _file_map(root: Path, max_entries: int) -> list[str]:
    entries: list[str] = []
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if any(part in _IGNORE for part in rel.parts):
            continue
        if len(rel.parts) > 2:   # depth-2 cap
            continue
        entries.append(rel.as_posix() + ("/" if p.is_dir() else ""))
        if len(entries) >= max_entries:
            entries.append("… (truncated)")
            break
    return entries


def build(workspace_root, max_entries: int = 200) -> str:
    root = Path(workspace_root)
    lines = ["# WORKSPACE ENVIRONMENT",
             f"Working directory: {root}",
             f"Platform: {platform.system()} {platform.release()}"]
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if branch:
        dirty = _git(root, "status", "--porcelain")
        n_dirty = len([ln for ln in dirty.splitlines() if ln.strip()])
        lines.append(f"Git branch: {branch} ({n_dirty} uncommitted file(s))")
        log = _git(root, "log", "-5", "--pretty=format:%h %s")
        if log:
            lines.append("Recent commits:\n" + log)
    lines.append("Files:")
    for e in _file_map(root, max_entries):
        lines.append(f"- {e}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run green**

Run: `pytest backend/tests/test_harness_env_context.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/harness/env_context.py backend/tests/test_harness_env_context.py
git commit -m "feat(harness): workspace environment-context builder"
```

---

## Task 13: Workspace registry

**Files:**
- Create: `backend/ocd_core/workspace_registry.py`
- Test: `backend/tests/test_harness_registry.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_harness_registry.py
from ocd_core import workspace_registry as wr


def test_register_and_get(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "_STORE", tmp_path / "workspaces.json")
    ws = wr.register(str(tmp_path / "proj"))
    assert ws["id"]
    got = wr.get(ws["id"])
    assert got["root"] == str((tmp_path / "proj"))


def test_list_recents_orders_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "_STORE", tmp_path / "workspaces.json")
    a = wr.register(str(tmp_path / "a"))
    b = wr.register(str(tmp_path / "b"))
    wr.touch(a["id"])   # a is now most-recent
    ids = [w["id"] for w in wr.list_recents()]
    assert ids[0] == a["id"] and b["id"] in ids


def test_get_unknown_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "_STORE", tmp_path / "workspaces.json")
    assert wr.get("nope") is None


def test_rules_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "_STORE", tmp_path / "workspaces.json")
    ws = wr.register(str(tmp_path / "p"))
    wr.set_rules(ws["id"], {"allow": ["bash(git *)"], "deny": [], "ask": []})
    assert wr.get(ws["id"])["rules"]["allow"] == ["bash(git *)"]
```

- [ ] **Step 2: Run red**

Run: `pytest backend/tests/test_harness_registry.py -q`
Expected: FAIL — no `workspace_registry`.

- [ ] **Step 3: Implement**

```python
# backend/ocd_core/workspace_registry.py
"""On-disk registry of code workspaces (id -> root path + rules + recents), stored as a
single atomic JSON file. IDs are short hex; roots are absolute. Used by the harness
routes and the agent turn to resolve a workspace_id to a root + its permission rules."""
from __future__ import annotations

import hashlib
from pathlib import Path

from . import config, jsonstore

_STORE = config.REPO_ROOT / "workspaces.json"
_DEFAULT_PROTECTED = [".env", ".env.*", "*.pem", "id_*"]


def _load() -> dict:
    return jsonstore.load_json(_STORE, {"workspaces": []})


def _save(data: dict) -> None:
    jsonstore.save_json(_STORE, data)


def _id_for(root: str) -> str:
    return hashlib.sha1(str(Path(root).resolve()).encode()).hexdigest()[:12]


def register(root: str) -> dict:
    data = _load()
    wid = _id_for(root)
    for w in data["workspaces"]:
        if w["id"] == wid:
            return w
    ws = {"id": wid, "root": str(Path(root).resolve()),
          "rules": {"allow": [], "deny": [], "ask": []},
          "protected": list(_DEFAULT_PROTECTED), "last_used": len(data["workspaces"])}
    data["workspaces"].append(ws)
    _save(data)
    return ws


def get(wid: str) -> dict | None:
    for w in _load()["workspaces"]:
        if w["id"] == wid:
            return w
    return None


def touch(wid: str) -> None:
    data = _load()
    hi = max((w.get("last_used", 0) for w in data["workspaces"]), default=0)
    for w in data["workspaces"]:
        if w["id"] == wid:
            w["last_used"] = hi + 1
    _save(data)


def set_rules(wid: str, rules: dict) -> None:
    data = _load()
    for w in data["workspaces"]:
        if w["id"] == wid:
            w["rules"] = {"allow": rules.get("allow", []), "deny": rules.get("deny", []),
                          "ask": rules.get("ask", [])}
    _save(data)


def list_recents() -> list[dict]:
    return sorted(_load()["workspaces"], key=lambda w: w.get("last_used", 0), reverse=True)
```

- [ ] **Step 4: Run green**

Run: `pytest backend/tests/test_harness_registry.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/workspace_registry.py backend/tests/test_harness_registry.py
git commit -m "feat(harness): on-disk workspace registry (roots, rules, recents)"
```

---

## Task 14: Wire file tools + plan + env + gate into `run_turn`

This is the integration task. It adds a `workspace_root` parameter, registers the harness tools when it's set, dispatches them, applies the rule gate before the existing HITL gate, snapshots files before edits, and emits the new events. Keep each sub-step small and re-run the existing HITL suite after.

**Files:**
- Modify: `backend/ocd_core/agent.py`
- Test: `backend/tests/test_agent_workspace.py`

- [ ] **Step 1: Write the failing integration test**

```python
# backend/tests/test_agent_workspace.py
"""Workspace tools flow through run_turn: an edit is gated, approved, applied, and a
file_diff event is emitted."""
import asyncio
import pytest
from ocd_core import agent, config, permissions, secrets
from ocd_core.llm import client as llm_client


class _FakeToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = type("F", (), {"name": name, "arguments": arguments})()

    def model_dump(self):
        return {"id": self.id, "type": "function",
                "function": {"name": self.function.name, "arguments": self.function.arguments}}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("OCD_SECRET_BACKEND", "memory")
    secrets.reset_store(); llm_client.reset_clients()
    monkeypatch.setattr(agent, "resolve_turn_client",
                        lambda model, provider=None: (object(), model, None))
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)
    monkeypatch.setattr(config, "PERMISSION_TIMEOUT_SEC", 2)
    yield
    secrets.reset_store(); llm_client.reset_clients()


def test_workspace_edit_emits_diff_and_applies(monkeypatch, tmp_path):
    (tmp_path / "a.txt").write_text("old\n")
    calls = iter([
        [_FakeToolCall("c1", "read_file", '{"path": "a.txt"}')],
        [_FakeToolCall("c2", "edit_file", '{"path":"a.txt","old_string":"old","new_string":"new"}')],
        [],
    ])

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
        async for ev in agent.run_turn("edit it", [], None, "m", effort="Low",
                                       workspace_root=str(tmp_path),
                                       permission_mode="acceptEdits", turn_id="t1"):
            events.append(ev)
        return events

    events = asyncio.run(scenario())
    assert (tmp_path / "a.txt").read_text() == "new\n"
    assert any(e.get("type") == "file_diff" for e in events)
    assert any(e.get("type") == "tool_call" for e in events)
```

- [ ] **Step 2: Run red**

Run: `pytest backend/tests/test_agent_workspace.py -q`
Expected: FAIL — `run_turn()` has no `workspace_root` kwarg.

- [ ] **Step 3a: Add the parameter + tool registration**

In `agent.py`, add `workspace_root: str | None = None` and `workspace_rules: dict | None = None` to `run_turn`'s signature (near `subagents: bool = False`). Where the tool list is assembled (around `agent.py:1299-1325`, the `tools.append(...)` block), add:

```python
    # Harness workspace tools (only when a folder is attached).
    ws_read_paths: set[str] = set()
    ws_plan = None
    if workspace_root:
        from .harness import workspace_fs as _wfs
        from .harness import plan_tool as _plan
        from .harness import rules as _rules
        from .harness import env_context as _envctx
        from .harness import checkpoints as _ckpt
        for spec in _wfs.FILE_TOOL_SPECS:
            tools.append(spec)
        tools.append(_plan.PLAN_TOOL_SPEC)
        ws_plan = _plan.Plan()
        # Effective ruleset = the workspace's own registry rules (user's explicit choices,
        # passed in by the route from workspace_registry) PLUS the workspace's
        # .claude/settings.json import. Precedence (deny>ask>allow) is evaluated across the
        # whole set, so concatenation order within a category is irrelevant.
        _claude = _rules.load_claude_ruleset(workspace_root)
        _reg = workspace_rules or {}
        ws_ruleset = _rules.RuleSet(
            allow=list(_reg.get("allow", [])) + _claude.allow,
            deny=list(_reg.get("deny", [])) + _claude.deny,
            ask=list(_reg.get("ask", [])) + _claude.ask)
        ws_ckpt = _ckpt.CheckpointStore(config.REPO_ROOT / "checkpoints" / (turn_id or "adhoc"))
```

Append the env-context section to the system prompt where the prompt is assembled (find where `system` / `sys_prompt` string is built in `run_turn`; append):

```python
        _env_section = _envctx.build(workspace_root)
        system = system + "\n\n" + _env_section  # use the actual local var name for the system prompt
```

- [ ] **Step 3b: Dispatch harness tools**

In the tool-execution path (where `_run_one_tool` is called per call, inside the `if calls:` block ~`agent.py:1652`), branch harness tools before the generic dispatch. The cleanest place is inside `_run_one_tool` itself — add at the top:

```python
async def _run_one_tool(name, args, tc_id, active_project, goal, top_k,
                        ...,  # keep existing params
                        workspace_root=None, ws_read_paths=None, ws_plan=None, ws_ckpt=None):
    if workspace_root and name in ("read_file", "edit_file", "write_file", "glob", "grep"):
        from .harness import workspace_fs as _wfs
        if name in ("edit_file", "write_file") and ws_ckpt is not None:
            ws_ckpt.snapshot_before_edit(_ckpt_turn, workspace_root, (args or {}).get("path", ""))
        out = _wfs.run_fs_tool(name, args, workspace_root, ws_read_paths if ws_read_paths is not None else set())
        result = out.get("content") or out.get("diff") or _json_compact(out)
        return {"id": tc_id, "name": name, "ok": out.get("ok", False), "result": result,
                "summary": "", "diff": out.get("diff"), "paths": out.get("paths")}
    if workspace_root and name == "task_plan" and ws_plan is not None:
        out = ws_plan.apply(args or {})
        return {"id": tc_id, "name": name, "ok": out.get("ok", False),
                "result": _json_compact(out), "summary": "", "plan": ws_plan.snapshot()}
    # ... existing dispatch unchanged ...
```

Pass the new kwargs where `_run_one_tool` is invoked (the `interim`/executor block ~`agent.py:1660-1700`). Thread `workspace_root=workspace_root, ws_read_paths=ws_read_paths, ws_plan=ws_plan, ws_ckpt=ws_ckpt`. For the checkpoint turn id, capture `_ckpt_turn = turn_id or "adhoc"` in `run_turn` and pass it through (or store on the store instance).

*Implementer note:* if threading many kwargs through the executor is noisy, wrap them in a small `ws_ctx` dataclass `{root, read_paths, plan, ckpt, turn}` and pass that single object. Keep the signature change minimal.

- [ ] **Step 3c: Apply the rule gate + emit events**

At the gate (`agent.py:~1629`), before the existing `permissions.requires_approval` check, insert the rule decision for workspace tools:

```python
            if workspace_root:
                from .harness import rules as _rules
                _decision = _rules.gate(name, args, perm_mode, ws_ruleset)
                if _decision == "deny":
                    yield {"type": "tool_error", "id": tc.id, "name": name,
                           "text": f"Blocked by permission rules/mode for {name}."}
                    blocked_outcomes.append({"id": tc.id, "name": name, "ok": False,
                        "skip_breaker": True,
                        "result": f"BLOCKED: '{name}' denied by the active permission mode/rules."})
                    continue
                if _decision == "allow":
                    calls.append((tc.id, name, args)); continue
                # _decision == "ask" -> fall through to the existing HITL prompt below
```

After a harness tool runs, emit `tool_call` and (for edits) `file_diff` and (for plan) `plan_update`. In the results-emitting loop (where `tool_result` events are yielded), add:

```python
            if res.get("name") in ("read_file","edit_file","write_file","glob","grep","task_plan"):
                yield {"type": "tool_call", "id": res["id"], "name": res["name"],
                       "ok": res.get("ok", False)}
                if res.get("diff"):
                    yield {"type": "file_diff", "id": res["id"], "diff": res["diff"]}
                if res.get("plan") is not None:
                    yield {"type": "plan_update", "items": res["plan"]}
            if workspace_root and res.get("name") in ("edit_file","write_file") and res.get("ok"):
                yield {"type": "checkpoint", "turn_id": turn_id}
```

- [ ] **Step 4: Run green (new test + existing HITL suite)**

Run: `pytest backend/tests/test_agent_workspace.py backend/tests/test_agent_hitl.py -q`
Expected: PASS (new workspace test green; existing HITL unaffected).

- [ ] **Step 5: Commit**

```bash
git add backend/ocd_core/agent.py backend/tests/test_agent_workspace.py
git commit -m "feat(harness): wire file tools + plan + rule gate + events into run_turn"
```

---

## Task 15: Schema + agent route wiring

**Files:**
- Modify: `backend/app/schemas.py`, `backend/app/routes/agent.py`
- Test: `backend/tests/test_agent_workspace.py` (route-level)

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_agent_workspace.py
from app.schemas import AgentTurnRequest


def test_schema_accepts_workspace_id_and_new_modes():
    req = AgentTurnRequest(goal="hi", model="m", workspace_id="abc123",
                           permission_mode="acceptEdits")
    assert req.workspace_id == "abc123"
    req2 = AgentTurnRequest(goal="hi", model="m", permission_mode="plan")
    assert req2.permission_mode == "plan"
```

- [ ] **Step 2: Run red**

Run: `pytest backend/tests/test_agent_workspace.py::test_schema_accepts_workspace_id_and_new_modes -q`
Expected: FAIL — `workspace_id` unknown / `plan` rejected by the validator.

- [ ] **Step 3: Implement**

In `schemas.py`, add to `AgentTurnRequest`:

```python
    workspace_id: str | None = None   # attaches a code workspace (harness tools)
```

Extend the `permission_mode` validator's accepted set to include `default`, `acceptEdits`, `plan`, `strict`, `bypass` (plus existing `auto`/`ask` aliases). Locate `_bound_permission_mode` (schemas.py:63) and widen its allowed set accordingly (keep the "None → default" behavior).

In `routes/agent.py`, resolve the workspace and thread it in:

```python
from ocd_core import workspace_registry
...
    ws_root = None
    ws_rules = None
    if req.workspace_id:
        ws = workspace_registry.get(req.workspace_id)
        if ws:
            ws_root = ws["root"]
            ws_rules = ws.get("rules")
            workspace_registry.touch(req.workspace_id)
...
            turn = agent.run_turn(
                    goal, history, req.project_id, req.model, proj_instr,
                    ...,
                    project_memory=proj_mem, images=req.images, style=req.style or "",
                    workspace_root=ws_root, workspace_rules=ws_rules)
```

- [ ] **Step 4: Run green**

Run: `pytest backend/tests/test_agent_workspace.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas.py backend/app/routes/agent.py backend/tests/test_agent_workspace.py
git commit -m "feat(harness): thread workspace_id through agent turn request"
```

---

## Task 16: Harness routes (workspace CRUD + checkpoints)

**Files:**
- Create: `backend/app/routes/harness.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_harness_routes.py`

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_harness_routes.py
import pytest
from fastapi.testclient import TestClient
from app.main import app
from ocd_core import workspace_registry as wr


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "_STORE", tmp_path / "workspaces.json")
    return TestClient(app)


def test_register_workspace(client, tmp_path):
    r = client.post("/workspaces", json={"root": str(tmp_path / "proj")})
    assert r.status_code == 200
    assert r.json()["id"]


def test_list_recents(client, tmp_path):
    client.post("/workspaces", json={"root": str(tmp_path / "a")})
    r = client.get("/workspaces")
    assert r.status_code == 200 and isinstance(r.json(), list)


def test_set_rules(client, tmp_path):
    wid = client.post("/workspaces", json={"root": str(tmp_path / "p")}).json()["id"]
    r = client.put(f"/workspaces/{wid}/rules",
                   json={"allow": ["bash(git *)"], "deny": [], "ask": []})
    assert r.status_code == 200
    assert client.get(f"/workspaces/{wid}").json()["rules"]["allow"] == ["bash(git *)"]
```

*Note:* if auth deps block these routes in the test client, follow the pattern the existing route tests use (e.g. `test_new_endpoints.py`) to satisfy `current_user` — reuse that fixture/override rather than inventing a new one.

- [ ] **Step 2: Run red**

Run: `pytest backend/tests/test_harness_routes.py -q`
Expected: FAIL — routes 404.

- [ ] **Step 3: Implement**

```python
# backend/app/routes/harness.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from ocd_core import workspace_registry
from pydantic import BaseModel

from ..deps import current_user

router = APIRouter()


class WorkspaceCreate(BaseModel):
    root: str


class RulesBody(BaseModel):
    allow: list[str] = []
    deny: list[str] = []
    ask: list[str] = []


@router.post("/workspaces")
def create_workspace(body: WorkspaceCreate, user: str = Depends(current_user)) -> dict:
    return workspace_registry.register(body.root)


@router.get("/workspaces")
def list_workspaces(user: str = Depends(current_user)) -> list[dict]:
    return workspace_registry.list_recents()


@router.get("/workspaces/{wid}")
def get_workspace(wid: str, user: str = Depends(current_user)) -> dict:
    ws = workspace_registry.get(wid)
    if not ws:
        raise HTTPException(404, "unknown workspace")
    return ws


@router.put("/workspaces/{wid}/rules")
def set_rules(wid: str, body: RulesBody, user: str = Depends(current_user)) -> dict:
    if not workspace_registry.get(wid):
        raise HTTPException(404, "unknown workspace")
    workspace_registry.set_rules(wid, body.model_dump())
    return {"ok": True}
```

Register in `main.py` next to the other `include_router` calls:

```python
from .routes import harness as harness_routes
app.include_router(harness_routes.router)
```

- [ ] **Step 4: Run green**

Run: `pytest backend/tests/test_harness_routes.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/harness.py backend/app/main.py backend/tests/test_harness_routes.py
git commit -m "feat(harness): workspace CRUD + rules routes"
```

---

## Task 17: Checkpoint list/restore route

**Files:**
- Modify: `backend/app/routes/harness.py`
- Test: `backend/tests/test_harness_routes.py`

- [ ] **Step 1: Write the failing tests**

```python
# add to backend/tests/test_harness_routes.py
from ocd_core import config
from ocd_core.harness import checkpoints


def test_checkpoint_list_and_restore(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REPO_ROOT", tmp_path)
    ws = tmp_path / "ws"; ws.mkdir()
    (ws / "a.txt").write_text("orig\n")
    store = checkpoints.CheckpointStore(tmp_path / "checkpoints" / "t1")
    store.snapshot_before_edit("t1", ws, "a.txt")
    (ws / "a.txt").write_text("changed\n")

    wid = client.post("/workspaces", json={"root": str(ws)}).json()["id"]
    lst = client.get(f"/workspaces/{wid}/checkpoints/t1")
    assert lst.status_code == 200 and lst.json()[0]["files"] == ["a.txt"]

    r = client.post(f"/workspaces/{wid}/checkpoints/t1/restore", json={"what": "files"})
    assert r.status_code == 200
    assert (ws / "a.txt").read_text() == "orig\n"
```

- [ ] **Step 2: Run red**

Run: `pytest backend/tests/test_harness_routes.py -q`
Expected: FAIL — checkpoint routes 404.

- [ ] **Step 3: Implement**

```python
# add to backend/app/routes/harness.py
from ocd_core import config
from ocd_core.harness.checkpoints import CheckpointStore


class RestoreBody(BaseModel):
    what: str = "files"   # files | conversation | both


def _store(turn_id: str) -> CheckpointStore:
    return CheckpointStore(config.REPO_ROOT / "checkpoints" / turn_id)


@router.get("/workspaces/{wid}/checkpoints/{turn_id}")
def list_checkpoints(wid: str, turn_id: str, user: str = Depends(current_user)) -> list[dict]:
    if not workspace_registry.get(wid):
        raise HTTPException(404, "unknown workspace")
    return _store(turn_id).list(turn_id)


@router.post("/workspaces/{wid}/checkpoints/{turn_id}/restore")
def restore_checkpoint(wid: str, turn_id: str, body: RestoreBody,
                       user: str = Depends(current_user)) -> dict:
    ws = workspace_registry.get(wid)
    if not ws:
        raise HTTPException(404, "unknown workspace")
    n = _store(turn_id).restore(turn_id, ws["root"], what=body.what)
    return {"ok": True, "restored": n}
```

- [ ] **Step 4: Run green**

Run: `pytest backend/tests/test_harness_routes.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routes/harness.py backend/tests/test_harness_routes.py
git commit -m "feat(harness): checkpoint list + restore routes"
```

---

## Task 18: Backend adversarial verify + full suite + lint

Security-critical gate per repo convention (Track-2). No new features — a verification checkpoint.

- [ ] **Step 1: Run the full backend suite**

Run: `pytest backend/tests -q`
Expected: PASS (all green, including the pre-existing suites).

- [ ] **Step 2: Lint**

Run: `ruff check backend/ocd_core/harness backend/app/routes/harness.py backend/ocd_core/workspace_registry.py`
Expected: no findings (fix any inline).

- [ ] **Step 3: Adversarial jail review (subagent)**

Dispatch a fresh subagent to *try to break* `resolve_in_workspace`: Windows junctions (`mklink /J`), 8.3 short names (`PROGRA~1`), UNC/`\\?\` prefixes, `..%2f` style inputs (already string-decoded by the caller so N/A, but confirm), a root that is itself a symlink, and case-collision on Windows. Any escape that reproduces → add a failing test, fix, re-run. Record the outcome ("jail HOLDS across N classes") in the commit body.

- [ ] **Step 4: Commit any fixes**

```bash
git add -A
git commit -m "test(harness): adversarial jail verify + suite/lint green"
```

---

## Task 19: Desktop event types + WorkspaceBar

**Files:**
- Modify: `desktop/src/api/events.ts`
- Create: `desktop/src/components/WorkspaceBar.tsx`, `desktop/src/components/WorkspaceBar.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// desktop/src/components/WorkspaceBar.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { WorkspaceBar } from "./WorkspaceBar";

describe("WorkspaceBar", () => {
  it("shows the folder name and mode selector", () => {
    render(<WorkspaceBar root="C:/proj/demo" mode="acceptEdits" onModeChange={() => {}} onDetach={() => {}} />);
    expect(screen.getByText(/demo/)).toBeInTheDocument();
    expect(screen.getByLabelText(/permission mode/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run red**

Run (in `desktop/`): `npm run test -- WorkspaceBar`
Expected: FAIL — no `WorkspaceBar`.

- [ ] **Step 3: Implement**

Add event types to `events.ts` (extend the existing event union — match its current style):

```ts
// desktop/src/api/events.ts — add to the AgentEvent union
export type ToolCallEvent = { type: "tool_call"; id: string; name: string; ok: boolean };
export type FileDiffEvent = { type: "file_diff"; id: string; diff: string };
export type PlanUpdateEvent = { type: "plan_update"; items: { id: number; subject: string; status: string }[] };
export type CheckpointEvent = { type: "checkpoint"; turn_id: string };
```

```tsx
// desktop/src/components/WorkspaceBar.tsx
type Mode = "default" | "acceptEdits" | "plan" | "strict" | "bypass";

export function WorkspaceBar({ root, mode, onModeChange, onDetach }: {
  root: string; mode: Mode;
  onModeChange: (m: Mode) => void; onDetach: () => void;
}) {
  const name = root.replace(/[/\\]+$/, "").split(/[/\\]/).pop() || root;
  return (
    <div className="workspace-bar">
      <span className="workspace-name" title={root}>📁 {name}</span>
      <label>
        <span className="sr-only">Permission mode</span>
        <select aria-label="permission mode" value={mode}
                onChange={(e) => onModeChange(e.target.value as Mode)}>
          <option value="default">Ask</option>
          <option value="acceptEdits">Accept edits</option>
          <option value="plan">Plan</option>
          <option value="strict">Strict</option>
          <option value="bypass">Bypass</option>
        </select>
      </label>
      <button onClick={onDetach}>Detach</button>
    </div>
  );
}
```

- [ ] **Step 4: Run green**

Run: `npm run test -- WorkspaceBar` then `npm run typecheck`
Expected: PASS + typecheck clean.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/api/events.ts desktop/src/components/WorkspaceBar.tsx desktop/src/components/WorkspaceBar.test.tsx
git commit -m "feat(harness): desktop workspace bar + harness event types"
```

---

## Task 20: Desktop ToolTimeline + FileDiffCard + PlanCard

**Files:**
- Create: `desktop/src/components/ToolTimeline.tsx` (+ test), `FileDiffCard.tsx` (+ test), `PlanCard.tsx` (+ test)

- [ ] **Step 1: Write the failing tests**

```tsx
// desktop/src/components/PlanCard.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { PlanCard } from "./PlanCard";

describe("PlanCard", () => {
  it("renders items with status", () => {
    render(<PlanCard items={[
      { id: 1, subject: "read code", status: "completed" },
      { id: 2, subject: "write test", status: "in_progress" },
    ]} />);
    expect(screen.getByText("read code")).toBeInTheDocument();
    expect(screen.getByText("write test")).toBeInTheDocument();
  });
});
```

```tsx
// desktop/src/components/FileDiffCard.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { FileDiffCard } from "./FileDiffCard";

describe("FileDiffCard", () => {
  it("renders added and removed lines", () => {
    render(<FileDiffCard diff={"--- a\n+++ a\n-old line\n+new line"} />);
    expect(screen.getByText(/new line/)).toBeInTheDocument();
    expect(screen.getByText(/old line/)).toBeInTheDocument();
  });
});
```

```tsx
// desktop/src/components/ToolTimeline.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { ToolTimeline } from "./ToolTimeline";

describe("ToolTimeline", () => {
  it("lists tool calls with status", () => {
    render(<ToolTimeline calls={[{ id: "c1", name: "read_file", ok: true }]} />);
    expect(screen.getByText(/read_file/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run red**

Run: `npm run test -- PlanCard FileDiffCard ToolTimeline`
Expected: FAIL — components missing.

- [ ] **Step 3: Implement**

```tsx
// desktop/src/components/PlanCard.tsx
export function PlanCard({ items }: { items: { id: number; subject: string; status: string }[] }) {
  const mark = (s: string) => (s === "completed" ? "✓" : s === "in_progress" ? "▸" : "○");
  return (
    <ul className="plan-card">
      {items.map((it) => (
        <li key={it.id} data-status={it.status}>
          <span aria-hidden>{mark(it.status)}</span> {it.subject}
        </li>
      ))}
    </ul>
  );
}
```

```tsx
// desktop/src/components/FileDiffCard.tsx
export function FileDiffCard({ diff }: { diff: string }) {
  return (
    <pre className="file-diff">
      {diff.split("\n").map((line, i) => {
        const cls = line.startsWith("+") && !line.startsWith("+++") ? "add"
          : line.startsWith("-") && !line.startsWith("---") ? "del" : "ctx";
        return <div key={i} className={`diff-line ${cls}`}>{line}</div>;
      })}
    </pre>
  );
}
```

```tsx
// desktop/src/components/ToolTimeline.tsx
export function ToolTimeline({ calls }: { calls: { id: string; name: string; ok: boolean }[] }) {
  return (
    <ol className="tool-timeline">
      {calls.map((c) => (
        <li key={c.id} data-ok={c.ok}>
          <code>{c.name}</code> {c.ok ? "✓" : "✗"}
        </li>
      ))}
    </ol>
  );
}
```

- [ ] **Step 4: Run green**

Run: `npm run test -- PlanCard FileDiffCard ToolTimeline` then `npm run typecheck`
Expected: PASS + clean.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/components/ToolTimeline.tsx desktop/src/components/ToolTimeline.test.tsx desktop/src/components/FileDiffCard.tsx desktop/src/components/FileDiffCard.test.tsx desktop/src/components/PlanCard.tsx desktop/src/components/PlanCard.test.tsx
git commit -m "feat(harness): desktop tool timeline, diff card, plan card"
```

---

## Task 21: Desktop RewindMenu + wire into Message/Composer

**Files:**
- Create: `desktop/src/components/RewindMenu.tsx` (+ test)
- Modify: `desktop/src/components/Message.tsx`, `desktop/src/components/Composer.tsx`, `desktop/src/api/client.ts`

- [ ] **Step 1: Write the failing test**

```tsx
// desktop/src/components/RewindMenu.test.tsx
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { RewindMenu } from "./RewindMenu";

describe("RewindMenu", () => {
  it("calls onRestore with the chosen scope", () => {
    const onRestore = vi.fn();
    render(<RewindMenu turnId="t1" onRestore={onRestore} />);
    fireEvent.click(screen.getByText(/restore files/i));
    expect(onRestore).toHaveBeenCalledWith("t1", "files");
  });
});
```

- [ ] **Step 2: Run red**

Run: `npm run test -- RewindMenu`
Expected: FAIL — no `RewindMenu`.

- [ ] **Step 3: Implement**

```tsx
// desktop/src/components/RewindMenu.tsx
export function RewindMenu({ turnId, onRestore }: {
  turnId: string; onRestore: (turnId: string, what: "files" | "conversation" | "both") => void;
}) {
  return (
    <div className="rewind-menu" role="menu">
      <button role="menuitem" onClick={() => onRestore(turnId, "files")}>Restore files</button>
      <button role="menuitem" onClick={() => onRestore(turnId, "conversation")}>Restore conversation</button>
      <button role="menuitem" onClick={() => onRestore(turnId, "both")}>Restore both</button>
    </div>
  );
}
```

Add an API client method (match `client.ts` style):

```ts
// desktop/src/api/client.ts
export async function restoreCheckpoint(workspaceId: string, turnId: string,
  what: "files" | "conversation" | "both") {
  return apiFetch(`/workspaces/${workspaceId}/checkpoints/${turnId}/restore`, {
    method: "POST", body: JSON.stringify({ what }),
  });
}
```

Mount `WorkspaceBar` in the composer (fed by app state holding the current workspace + mode) and render `ToolTimeline`/`FileDiffCard`/`PlanCard`/`RewindMenu` inside `Message.tsx` from the accumulated events for that message. Keep the wiring minimal; the components already have tests. Follow the existing event-accumulation pattern in `Message.tsx` for reading `tool_call`/`file_diff`/`plan_update` off the message's event list.

- [ ] **Step 4: Run green + full desktop gate**

Run (in `desktop/`): `npm run typecheck && npm run test && npm run build`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add desktop/src
git commit -m "feat(harness): rewind menu + wire workspace UI into chat"
```

---

## Task 22: End-to-end smoke + docs

**Files:**
- Modify: `README.md` (feature note), `docs/superpowers/specs/2026-07-20-harness-design.md` (mark P1 shipped)
- Test: full suites

- [ ] **Step 1: Backend + desktop full gates**

Run: `pytest backend/tests -q`
Run: `cd desktop && npm run typecheck && npm run test && npm run build`
Expected: all green.

- [ ] **Step 2: Manual smoke (documented, not automated)**

Start backend + desktop (per `run` skill / `.claude/launch.json`), attach a throwaway folder, ask the agent to "add a hello function to a new file and a test, then run it". Verify: tool timeline shows read/write/edit, a diff renders, `acceptEdits` auto-applies, `plan` mode blocks a write, rewind restores. Capture nothing sensitive.

- [ ] **Step 3: Docs**

Add a short "Harness (code workspaces)" section to `README.md` describing attach-a-folder, modes, and rewind. In the spec file, change the P1 row note to "shipped (feat/harness)".

- [ ] **Step 4: Commit**

```bash
git add README.md docs/superpowers/specs/2026-07-20-harness-design.md
git commit -m "docs(harness): document code-workspace harness (P1)"
```

- [ ] **Step 5: Open PR**

```bash
git push -u origin feat/harness
gh pr create --base main --title "feat(harness): agentic coding core (P1)" \
  --body "Implements Phase 1 of docs/superpowers/specs/2026-07-20-harness-design.md: workspace path jail, file tool suite, permission modes + rules, checkpoints/rewind, plan tool, env context, and desktop UI. Multi-provider loop and Track-2 safety untouched. P2-P4 tracked in the spec."
```

---

## Self-Review Notes (for the executor)

- **Spec coverage:** §4 package layout → Tasks 1-13; §5 jail → Task 2 + Task 18 verify; §6 tools → Tasks 3-7; §7 permissions → Tasks 8-9 + gate in 14; §8 checkpoints → Tasks 10, 17; §9 plan → Task 11; §10 env → Task 12; §11 events/UI → Tasks 19-21; §13 testing → every task + Task 18; §12 audit → uses existing `observability.audit` in the gate (add an `audit({"event":"harness_gate","tool":name,"decision":...})` call alongside the rule decision in Task 14 Step 3c).
- **Deferred to later phases (not P1):** hooks, subagents-as-defined-agents, compaction rewrite, memory hierarchy, container sandbox, ACP — do not implement here.
- **Integration risk:** Task 14 is the one large task. If `_run_one_tool`'s signature is threaded through an executor that's awkward to extend, use the `ws_ctx` dataclass suggestion. Re-run `test_agent_hitl.py` after every sub-step of Task 14 — the existing HITL gate must stay green.
- **`system` prompt variable:** Task 14 Step 3a appends env context to "the system prompt local var" — the executor must open `run_turn` and use the actual variable name (grep for where the system/developer message is assembled; it may be `sys_prompt`, `system`, or built inline into `messages[0]`).
