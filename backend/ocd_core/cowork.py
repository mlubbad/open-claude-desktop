"""Cowork — delegated background agent tasks.

You hand the agent a goal and it works on it autonomously to completion while you do
something else; a task list shows status and each task keeps its full event transcript.
Because there's no human in the loop to answer HITL prompts, background tasks run with
``permission_mode="auto"`` (the route wires that).

This module is transport-agnostic: ``CoworkManager`` runs an async *event generator*
(any coroutine that yields the frozen agent event dicts) as a background asyncio task and
accumulates its events. The route supplies ``agent.run_turn(...)``; tests supply a fake
generator, so the whole lifecycle is verifiable without an LLM.
"""
from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def title_of(goal: str) -> str:
    t = " ".join((goal or "").split())
    return (t[:60] + "…") if len(t) > 60 else (t or "Untitled task")


@dataclass
class Task:
    id: str
    goal: str
    title: str
    status: str = "running"  # running | done | error | cancelled
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    events: list[dict] = field(default_factory=list)
    error: str | None = None
    handle: asyncio.Task | None = field(default=None, repr=False)

    def answer(self) -> str:
        """The final answer text, reassembled from streamed answer deltas."""
        return "".join(e.get("text", "") for e in self.events
                       if e.get("type") == "delta" and e.get("scope") == "answer")

    def summary(self) -> dict:
        return {"id": self.id, "title": self.title, "status": self.status,
                "created_at": self.created_at, "updated_at": self.updated_at,
                "events": len(self.events)}

    def detail(self) -> dict:
        return {**self.summary(), "goal": self.goal, "error": self.error,
                "event_list": list(self.events), "answer": self.answer()}


class CoworkManager:
    """In-memory registry of background agent tasks (one process; not persisted)."""

    def __init__(self) -> None:
        self._tasks: dict[str, Task] = {}

    async def _run(self, task: Task, gen_factory: Callable[[], AsyncIterator[dict]]) -> None:
        try:
            async for ev in gen_factory():
                task.events.append(ev)
                task.updated_at = _now_iso()
                if ev.get("type") == "error":
                    task.error = ev.get("text")
            task.status = "error" if task.error else "done"
        except asyncio.CancelledError:
            task.status = "cancelled"
            raise
        except Exception as e:  # noqa: BLE001 - surface any failure as task state
            task.status = "error"
            task.error = str(e)[:300]
        finally:
            task.updated_at = _now_iso()

    def start(self, goal: str, gen_factory: Callable[[], AsyncIterator[dict]]) -> Task:
        """Register a task and launch it on the running event loop."""
        task = Task(id=uuid.uuid4().hex[:12], goal=goal, title=title_of(goal))
        self._tasks[task.id] = task
        task.handle = asyncio.create_task(self._run(task, gen_factory))
        return task

    def list(self) -> list[dict]:
        return [t.summary() for t in sorted(self._tasks.values(),
                                            key=lambda t: t.created_at, reverse=True)]

    def get(self, task_id: str) -> dict | None:
        t = self._tasks.get(task_id)
        return t.detail() if t else None

    def cancel(self, task_id: str) -> bool:
        t = self._tasks.get(task_id)
        if not t or t.status != "running" or t.handle is None:
            return False
        t.handle.cancel()
        return True

    async def aclose(self) -> None:
        """Cancel all running tasks (shutdown)."""
        for t in self._tasks.values():
            if t.handle and not t.handle.done():
                t.handle.cancel()
                with contextlib.suppress(Exception):
                    await t.handle


manager = CoworkManager()
