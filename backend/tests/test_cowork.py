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
