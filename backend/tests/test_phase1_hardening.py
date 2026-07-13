"""Phase 1 ship-blocker hardening (production-readiness audit follow-up).

Covers: fail-closed permission/approval enums, sanitized text_editor/memory roots (F-06),
project-context hydration for background/scheduled runs (F-19), and the packaged-desktop
CORS origins (part of F-01 — the CSP side is guarded by a desktop test)."""
from ocd_core import agent, integrations, permissions


# ---- fail-closed permission gate ---------------------------------------------------
def test_requires_approval_fails_closed_on_unknown_mode():
    # "auto" is the only non-prompting mode; strict prompts always; ask gates sensitives.
    assert permissions.requires_approval("bash", "auto") is False
    assert permissions.requires_approval("bash", "strict") is True
    assert permissions.requires_approval("bash", "ask") is True
    assert permissions.requires_approval("web_search", "ask") is False
    # A non-empty unrecognized value (typo, injected value) must NOT drop to the ungated
    # path — it fails closed to "prompt for everything". (None/"" still mean the historic
    # "auto" default at this low level; the security default for unset is chosen upstream
    # in run_turn, which resolves it to the persisted "ask".)
    for bogus in ("aks", "prompt", "high", "yolo", "manual"):
        assert permissions.requires_approval("bash", bogus) is True, bogus


def test_cowork_approval_enum_coerces_unknown_to_gated():
    from app.routes.cowork import CoworkStart
    mk = lambda a: CoworkStart(goal="g", model="m", approval=a).approval  # noqa: E731
    assert mk("skip") == "skip"
    assert mk("manual") == "manual"
    assert mk("Manual") == "manual"          # case-normalized
    assert mk("manaul") == "manual"          # typo → gated, never silently autonomous
    assert mk("") == "skip"                   # empty/unset → the autonomous default
    assert CoworkStart(goal="g", model="m").approval == "skip"  # default unchanged


def test_permission_mode_enum_coerces_unknown_to_strict():
    from app.schemas import AgentTurnRequest
    mk = lambda pm: AgentTurnRequest(goal="g", model="m", permission_mode=pm).permission_mode  # noqa: E731
    assert mk("ask") == "ask"
    assert mk("Strict") == "strict"
    assert mk("auto") == "auto"
    assert mk("bogus") == "strict"           # unknown → fail closed
    assert mk(None) is None                  # None → server default (unchanged)


# ---- F-06: text_editor / memory roots are sanitized --------------------------------
def test_tool_roots_are_jailed_to_a_sanitized_project():
    sandbox = integrations.SANDBOX_ROOT.resolve()
    memory = integrations.MEMORY_ROOT.resolve()
    # A drive-anchored (Windows) or traversal project id must not escape the jail.
    for pid in ("C:/", "../../etc", "..\\..\\Windows", "/etc", "a/../../b"):
        te = agent._tool_root("text_editor", pid).resolve()
        me = agent._tool_root("memory", pid).resolve()
        te.relative_to(sandbox)   # raises if the root escaped the sandbox
        me.relative_to(memory)
    # None/empty falls back to the canonical general project, still inside the jail.
    agent._tool_root("text_editor", None).resolve().relative_to(sandbox)


# ---- F-19: background/scheduled runs inherit project instructions + memory ---------
def test_project_context_hydrates_when_not_passed(db):
    from ocd_core import projects
    p = projects.create_project("Rules")
    projects.save_project_instructions(p["id"], "never touch production")
    projects.save_project_memory(p["id"], "prefers TypeScript")
    # None (the Cowork/scheduler case) → hydrated from the project.
    instr, mem = agent._project_context(p["id"], None, None)
    assert instr == "never touch production" and mem == "prefers TypeScript"
    # Explicit values (including "") are respected — interactive/subagent callers.
    assert agent._project_context(p["id"], "", "") == ("", "")
    assert agent._project_context(p["id"], "x", "y") == ("x", "y")
    # No project → empty, never a crash.
    assert agent._project_context(None, None, None) == ("", "")


def test_project_context_degrades_when_store_unavailable(monkeypatch):
    # Reproduces the case where run_turn is driven with a project_id but the project
    # store can't be read (schema not created / DB down): hydration must degrade to
    # empty context instead of crashing the turn.
    from ocd_core import projects

    def boom(*_a, **_k):
        raise RuntimeError("no such table: project")

    monkeypatch.setattr(projects, "get_project_instructions", boom)
    monkeypatch.setattr(projects, "get_project_memory", boom)
    assert agent._project_context("proj-1", None, None) == ("", "")
    # An explicitly-passed value is still honored even when the store would error.
    assert agent._project_context("proj-1", "keep", None) == ("keep", "")


# ---- F-01 (CORS half): packaged Tauri origins are allowed by default ---------------
def test_default_cors_allows_packaged_tauri_origins():
    from app.main import app
    from fastapi.testclient import TestClient
    c = TestClient(app)
    for origin in ("tauri://localhost", "http://tauri.localhost"):
        r = c.get("/healthz", headers={"Origin": origin})
        assert r.headers.get("access-control-allow-origin") == origin, origin
