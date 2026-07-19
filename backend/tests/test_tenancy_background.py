"""Workspace tenancy — background Cowork/scheduler runs (SaaS slice 3).

Slices 1-2 scope everything a REQUEST touches, but a background run executes outside a
request: a Cowork task launched by the scheduler ticker inherits the ticker's ambient
context (`local`), so without an explicit re-bind a wsA automation would run as `local`.
These tests pin that the owning workspace is captured and re-bound for the whole run —
and that locally (flag off) nothing changes.
"""
import asyncio

from ocd_core import cowork, scheduler, tenancy


async def _done_gen():
    yield {"type": "done"}


# ---- Cowork ---------------------------------------------------------------------------

def test_start_local_leaves_no_workspace(monkeypatch):
    """Flag off → the task carries no workspace and its persisted JSON is unchanged."""
    async def go():
        mgr = cowork.CoworkManager()
        task = mgr.start("g", lambda: _done_gen())
        await task.handle
        return task
    task = asyncio.run(go())
    assert task.workspace is None
    assert "workspace" not in task.persisted()  # local on-disk shape is byte-for-byte


def test_start_captures_ambient_workspace(db, monkeypatch):
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    async def go():
        mgr = cowork.CoworkManager()
        with tenancy.use_workspace("wsA"):
            task = mgr.start("g", lambda: _done_gen())
        await task.handle
        return task
    task = asyncio.run(go())
    assert task.workspace == "wsA"
    assert task.persisted()["workspace"] == "wsA"


def test_run_rebinds_task_workspace_from_a_local_context(monkeypatch):
    """The core fix: even when _run executes in the ambient `local` context (the scheduler
    ticker case), the generator is scoped to the task's OWN workspace — not `local`."""
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    seen = []

    async def gen():
        seen.append(tenancy.current_workspace())
        yield {"type": "done"}

    async def go():
        mgr = cowork.CoworkManager()
        task = cowork.Task(id="t1", goal="g", title="g", workspace="wsA")
        mgr._tasks["t1"] = task
        # No use_workspace() wrapper here → ambient is the default `local`.
        assert tenancy.current_workspace() == tenancy.LOCAL_WORKSPACE
        await mgr._run(task, lambda: gen())

    asyncio.run(go())
    assert seen == ["wsA"]  # re-bound to the task's workspace, not the ambient one


# ---- scheduler ------------------------------------------------------------------------

def test_schedule_stamps_and_persists_workspace(db, monkeypatch, tmp_path):
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    store = scheduler.ScheduleStore(tmp_path / "schedules.json")
    svc = scheduler.SchedulerService(store=store, launch=lambda s: "t")
    with tenancy.use_workspace("wsA"):
        created = svc.add(goal="g", kind="interval", every_seconds=60)
        # Survives the round-trip through the store. Under enforcement the
        # store reads back scoped to the CURRENT workspace, so load inside wsA.
        assert store.load()[0].workspace == "wsA"
    assert created["workspace"] == "wsA"


def test_schedule_add_local_has_no_workspace(tmp_path):
    store = scheduler.ScheduleStore(tmp_path / "schedules.json")
    svc = scheduler.SchedulerService(store=store, launch=lambda s: "t")
    created = svc.add(goal="g", kind="interval", every_seconds=60)  # flag off
    assert created["workspace"] is None


def test_default_launch_runs_under_the_schedules_workspace(db, monkeypatch):
    """End-to-end: the ticker (local context) fires a wsA automation, and the launched
    Cowork run executes as wsA — proving add()→launch()→start()→_run() carries it."""
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    seen = []

    def fake_run_turn(*_a, **_k):
        async def gen():
            seen.append(tenancy.current_workspace())
            yield {"type": "done"}
        return gen()

    monkeypatch.setattr(scheduler.agent, "run_turn", fake_run_turn)
    # Opik tap is opt-in; force it to a pass-through so the fake generator is what runs.
    monkeypatch.setattr(scheduler.opik_tracing, "traced", lambda gen, **_k: gen)

    s = scheduler.Schedule(id="s1", goal="g", workspace="wsA")

    async def go():
        assert tenancy.current_workspace() == tenancy.LOCAL_WORKSPACE  # ticker ambient
        tid = scheduler.default_launch(s)
        await cowork.manager._tasks[tid].handle

    asyncio.run(go())
    assert seen == ["wsA"]
