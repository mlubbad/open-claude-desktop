"""Cowork background task manager: lifecycle (running→done), event capture, error and
cancel paths, and the /cowork routes plumbing (with a fake runner — no LLM)."""
import asyncio
import contextlib

import pytest
from fastapi.testclient import TestClient
from ocd_core import cowork


async def _answer_gen():
    yield {"type": "answer_open"}
    yield {"type": "delta", "scope": "answer", "text": "hello"}
    yield {"type": "delta", "scope": "answer", "text": " world"}
    yield {"type": "done"}


async def _error_gen():
    yield {"type": "answer_open"}
    yield {"type": "error", "text": "boom"}


async def _raise_gen():
    yield {"type": "answer_open"}
    raise RuntimeError("kaboom")


async def _slow_gen():
    yield {"type": "answer_open"}
    await asyncio.sleep(30)
    yield {"type": "done"}


def test_title_of():
    assert cowork.title_of("  do   a thing  ") == "do a thing"
    assert cowork.title_of("") == "Untitled task"
    assert cowork.title_of("x" * 100).endswith("…")


def test_task_runs_to_completion_and_captures_events():
    async def go():
        mgr = cowork.CoworkManager()
        task = mgr.start("do a thing", lambda: _answer_gen())
        assert task.status == "running"
        await task.handle
        return mgr, task.id

    mgr, tid = asyncio.run(go())
    detail = mgr.get(tid)
    assert detail["status"] == "done"
    assert detail["answer"] == "hello world"
    assert detail["events"] == 4
    assert detail["title"] == "do a thing"


def test_error_event_marks_task_error():
    async def go():
        mgr = cowork.CoworkManager()
        t = mgr.start("g", lambda: _error_gen())
        await t.handle
        return mgr.get(t.id)

    d = asyncio.run(go())
    assert d["status"] == "error" and d["error"] == "boom"


def test_raised_exception_marks_task_error():
    async def go():
        mgr = cowork.CoworkManager()
        t = mgr.start("g", lambda: _raise_gen())
        await t.handle
        return mgr.get(t.id)

    d = asyncio.run(go())
    assert d["status"] == "error" and "kaboom" in d["error"]


def test_cancel_running_task():
    async def go():
        mgr = cowork.CoworkManager()
        t = mgr.start("g", lambda: _slow_gen())
        await asyncio.sleep(0.05)  # let it reach the sleep
        ok = mgr.cancel(t.id)
        with contextlib.suppress(asyncio.CancelledError):
            await t.handle
        return ok, mgr.get(t.id)

    ok, d = asyncio.run(go())
    assert ok is True and d["status"] == "cancelled"


def test_cancel_unknown_task_is_false():
    mgr = cowork.CoworkManager()
    assert mgr.cancel("nope") is False


def test_list_is_newest_first():
    async def go():
        mgr = cowork.CoworkManager()
        a = mgr.start("first", lambda: _answer_gen())
        await a.handle
        b = mgr.start("second", lambda: _answer_gen())
        await b.handle
        return mgr.list()

    items = asyncio.run(go())
    assert [i["title"] for i in items][0] == "second"


@pytest.fixture
def client(monkeypatch):
    # Fake agent.run_turn so the route needs no LLM; reset the shared manager.
    from ocd_core import cowork as cw
    monkeypatch.setattr(cw, "manager", cw.CoworkManager())

    def fake_run_turn(*a, **k):
        return _answer_gen()

    from app.routes import cowork as cowork_route
    monkeypatch.setattr(cowork_route.agent, "run_turn", fake_run_turn)
    from app.main import app
    return TestClient(app)


def test_cowork_routes_plumbing(client):
    started = client.post("/cowork", json={"goal": "summarize the repo", "model": "glm-4-plus"})
    assert started.status_code == 200
    tid = started.json()["id"]
    assert started.json()["title"] == "summarize the repo"

    listed = client.get("/cowork").json()
    assert any(t["id"] == tid for t in listed)

    detail = client.get(f"/cowork/{tid}").json()
    assert detail["goal"] == "summarize the repo"

    assert client.get("/cowork/does-not-exist").status_code == 404
    assert client.post("/cowork", json={"goal": "", "model": "m"}).status_code == 400
    assert "cancelled" in client.post(f"/cowork/{tid}/cancel").json()


# --------------------------------------------------------------------------- #
#  P1-8: durable persistence, approval mode, tool parity, derived rail data
# --------------------------------------------------------------------------- #
def test_tasks_persist_across_a_restart(tmp_path, monkeypatch):
    """A completed task survives a new manager reading the same store; a task caught
    mid-run reloads as 'interrupted' rather than a phantom 'running'."""
    store = tmp_path / "cw.json"
    monkeypatch.setattr(cowork, "_STORE_PATH", store)

    async def go():
        mgr = cowork.CoworkManager()
        done = mgr.start("finished", lambda: _answer_gen())
        await done.handle
        # Simulate a running task that never got to persist a terminal status.
        running = cowork.Task(id="live1", goal="live", title="live", status="running")
        mgr._tasks["live1"] = running
        mgr._save()
        return done.id

    done_id = asyncio.run(go())

    reborn = cowork.CoworkManager()  # a "restart" reading the same file
    ids = {t["id"]: t for t in reborn.list()}
    assert ids[done_id]["status"] == "done"
    assert reborn.get(done_id)["answer"] == "hello world"
    assert ids["live1"]["status"] == "interrupted"  # can't resume; not a fake 'running'


def test_clear_finished_keeps_running():
    async def go():
        mgr = cowork.CoworkManager()
        d = mgr.start("done", lambda: _answer_gen())
        await d.handle
        r = mgr.start("slow", lambda: _slow_gen())
        await asyncio.sleep(0.05)
        removed = mgr.clear_finished()
        alive = [t["id"] for t in mgr.list()]
        mgr.cancel(r.id)
        with contextlib.suppress(asyncio.CancelledError):
            await r.handle
        return removed, alive, d.id, r.id

    removed, alive, done_id, run_id = asyncio.run(go())
    assert removed == 1
    assert done_id not in alive and run_id in alive


def test_manual_approval_wires_a_turn_id(client, monkeypatch):
    """approval=manual runs with permission_mode=ask + a turn_id (a live HITL gate),
    while skip stays autonomous."""
    captured = {}

    def fake_run_turn(*a, **k):
        captured.clear()
        captured.update(k)
        return _answer_gen()

    from app.routes import cowork as cowork_route
    monkeypatch.setattr(cowork_route.agent, "run_turn", fake_run_turn)

    r = client.post("/cowork", json={"goal": "build it", "model": "m", "approval": "manual"})
    assert r.json()["approval"] == "manual"
    assert captured["permission_mode"] == "ask" and captured["turn_id"]
    # The full autonomous toolset incl. the code/file tools is on for background work.
    assert captured["code_exec"] and captured["bash"] and captured["text_editor"]

    client.post("/cowork", json={"goal": "browse it", "model": "m"})  # default skip
    assert captured["permission_mode"] == "auto" and captured["turn_id"] is None


def test_clear_route(client):
    client.post("/cowork", json={"goal": "one", "model": "m"})
    assert client.post("/cowork/clear").json()["cleared"] >= 0


def test_derive_progress_and_files():
    events = [
        {"type": "think_open", "phase": "plan"},
        {"type": "think_close"},
        {"type": "files", "files": [{"name": "out.csv"}, {"name": "chart.png"}]},
        {"type": "artifact_open", "id": "a1", "title": "Report", "kind": "markdown"},
        {"type": "think_open", "phase": "verify"},  # still open → not done
    ]
    progress = cowork._derive_progress(events)
    assert progress[0] == {"label": "Planning the approach", "done": True}
    assert progress[1] == {"label": "Verifying the result", "done": False}
    files = {f["name"] for f in cowork._derive_files(events)}
    assert files == {"out.csv", "chart.png", "Report"}


def test_scheduled_launch_has_tool_parity(monkeypatch, tmp_path):
    """A scheduled automation launches with the code/file tools enabled so it can
    actually produce artifacts (P1-8), at permission_mode=auto."""
    from ocd_core import scheduler
    monkeypatch.setattr(cowork, "_STORE_PATH", tmp_path / "s.json")
    monkeypatch.setattr(scheduler, "cowork", cowork)
    captured = {}

    async def go():
        def fake_run_turn(*a, **k):
            captured.update(k)
            return _answer_gen()

        monkeypatch.setattr(scheduler.agent, "run_turn", fake_run_turn)
        monkeypatch.setattr(scheduler.opik_tracing, "traced",
                            lambda gen, **kw: gen)
        s = scheduler.Schedule(id="s1", goal="daily digest", model="m")
        tid = scheduler.default_launch(s)
        await cowork.manager._tasks[tid].handle

    asyncio.run(go())
    assert captured["permission_mode"] == "auto"
    assert captured["code_exec"] and captured["bash"] and captured["text_editor"]
