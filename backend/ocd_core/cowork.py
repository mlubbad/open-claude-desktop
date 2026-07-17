"""Cowork — delegated background agent tasks.

You hand the agent a goal and it works on it autonomously to completion while you do
something else; a task list shows status and each task keeps its full event transcript.

Approval mode (P1-8):
  * ``skip``   — the task runs fully autonomously (``permission_mode="auto"``), the
    original behavior. Best for trusted, unattended work.
  * ``manual`` — the task runs with a live HITL gate (``permission_mode="ask"`` + a
    ``turn_id``): it pauses on sensitive actions, surfacing an ``approval_required``
    event in its transcript that the task-detail view resolves through the existing
    ``/agent/turn/{turn_id}/permission`` endpoint.

Durability (P1-8): tasks + their event transcripts are persisted to a JSON store
(atomic writes via jsonstore) so a backend restart doesn't lose a completed run's
work. A task that was still ``running`` when the process died is reloaded as
``interrupted`` — its handle is gone, so it can't resume, but its transcript survives.

This module stays transport-agnostic: ``CoworkManager`` runs an async *event
generator* (any coroutine that yields the frozen agent event dicts) as a background
asyncio task and accumulates its events. The route supplies ``agent.run_turn(...)``;
tests supply a fake generator, so the whole lifecycle is verifiable without an LLM.
"""
from __future__ import annotations

import asyncio
import contextlib
import time
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import config, jsonstore, tenancy, workspace_store

# Bound a single task's stored transcript so one runaway task can't grow the store
# without limit; the head is kept (the goal + early plan) plus the recent tail.
_MAX_STORED_EVENTS = 4000
_STORE_PATH = Path(config.REPO_ROOT) / "cowork_tasks.json"
# Min seconds between incremental transcript flushes of a running task (see _run).
_FLUSH_INTERVAL_SEC = 3.0


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def title_of(goal: str) -> str:
    t = " ".join((goal or "").split())
    return (t[:60] + "…") if len(t) > 60 else (t or "Untitled task")


def _derive_files(events: list[dict]) -> list[dict]:
    """The workspace files a task touched, for the detail rail: produced code-exec
    files and created/updated artifacts, de-duplicated by name (latest wins)."""
    out: dict[str, dict] = {}
    for ev in events:
        t = ev.get("type")
        if t == "files":
            for f in ev.get("files", []):
                name = f.get("name") if isinstance(f, dict) else str(f)
                if name:
                    out[name] = {"name": name, "kind": "file"}
        elif t == "artifact_open":
            title = ev.get("title") or ev.get("id")
            if title:
                out[title] = {"name": title, "kind": ev.get("kind") or "artifact"}
    return list(out.values())


def _derive_progress(events: list[dict]) -> list[dict]:
    """A lightweight progress checklist for the detail rail, reconstructed from the
    thinking phases the turn emitted (plan / verify) — the closest signal the event
    stream carries to Claude Desktop's step list. Each is {label, done}."""
    steps: list[dict] = []
    open_phase: str | None = None
    for ev in events:
        t = ev.get("type")
        if t == "think_open":
            open_phase = ev.get("phase") or "thinking"
            label = {"plan": "Planning the approach",
                     "verify": "Verifying the result"}.get(open_phase,
                                                            open_phase.capitalize())
            steps.append({"label": label, "done": False})
        elif t == "think_close" and steps and open_phase is not None:
            steps[-1]["done"] = True
            open_phase = None
    return steps


@dataclass
class Task:
    id: str
    goal: str
    title: str
    status: str = "running"  # running | done | error | cancelled | interrupted
    approval: str = "skip"   # skip (auto) | manual (HITL gate live)
    turn_id: str | None = None
    project_id: str | None = None
    # The workspace that owns this run, captured at start() when multi-tenancy is enforced
    # (else None). Persisted so the owning tenant is re-bound for the whole background run,
    # even for a scheduler-launched task whose ambient context would otherwise be `local`.
    workspace: str | None = None
    model: str = ""
    provider: str | None = None
    effort: str = "High"
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
                "approval": self.approval, "project_id": self.project_id,
                "created_at": self.created_at, "updated_at": self.updated_at,
                "events": len(self.events)}

    def detail(self) -> dict:
        return {**self.summary(), "goal": self.goal, "error": self.error,
                "turn_id": self.turn_id, "event_list": list(self.events),
                "answer": self.answer(), "files": _derive_files(self.events),
                "progress": _derive_progress(self.events)}

    def persisted(self) -> dict:
        """The on-disk shape: metadata + a bounded event transcript (no live handle)."""
        evs = self.events
        if len(evs) > _MAX_STORED_EVENTS:
            head = _MAX_STORED_EVENTS // 4
            evs = [*evs[:head],
                   {"type": "delta", "scope": "answer",
                    "text": f"\n… [{len(evs) - _MAX_STORED_EVENTS} events truncated] …\n"},
                   *evs[-(_MAX_STORED_EVENTS - head):]]
        return {"id": self.id, "goal": self.goal, "title": self.title,
                "status": self.status, "approval": self.approval,
                "turn_id": self.turn_id, "project_id": self.project_id,
                # Only emitted for a non-local tenant, so a local task's JSON is unchanged.
                **({"workspace": self.workspace} if self.workspace else {}),
                "model": self.model, "provider": self.provider, "effort": self.effort,
                "created_at": self.created_at, "updated_at": self.updated_at,
                "error": self.error, "events": evs}

    @classmethod
    def from_persisted(cls, d: dict) -> Task:
        # A task caught mid-run by a restart can't resume (its handle is gone), so it
        # is reloaded as 'interrupted' rather than a phantom 'running'.
        status = d.get("status", "done")
        if status == "running":
            status = "interrupted"
        return cls(
            id=d["id"], goal=d.get("goal", ""), title=d.get("title") or title_of(d.get("goal", "")),
            status=status, approval=d.get("approval", "skip"), turn_id=d.get("turn_id"),
            project_id=d.get("project_id"), workspace=d.get("workspace"), model=d.get("model", ""),
            provider=d.get("provider"), effort=d.get("effort", "High"),
            created_at=d.get("created_at", _now_iso()), updated_at=d.get("updated_at", _now_iso()),
            events=list(d.get("events") or []), error=d.get("error"))


class CoworkManager:
    """Registry of background agent tasks, persisted to a JSON store so completed runs
    survive a restart."""

    def __init__(self, store_path: Path | None = None) -> None:
        self._tasks: dict[str, Task] = {}
        self._store_path = store_path or _STORE_PATH
        self._load()

    # -- persistence -------------------------------------------------------- #
    def _load(self) -> None:
        for d in jsonstore.load_json(self._store_path, []):
            if isinstance(d, dict) and d.get("id"):
                t = Task.from_persisted(d)
                self._tasks[t.id] = t

    def _save(self) -> None:
        # Newest first, and cap the number of retained tasks so the store is bounded.
        ordered = sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)
        if tenancy.enforcing():
            for task in ordered[:200]:
                if tenancy.owns(task.workspace):
                    workspace_store.upsert_cowork(task.persisted())
            return
        jsonstore.save_json(self._store_path, [t.persisted() for t in ordered[:200]])

    # -- lifecycle ---------------------------------------------------------- #
    async def _run(self, task: Task, gen_factory: Callable[[], AsyncIterator[dict]]) -> None:
        last_flush = time.monotonic()
        # Re-bind the owning workspace for the whole run so every scoped call inside the
        # agent turn (projects/conversations/secrets/settings/vectors) sees the right
        # tenant. A request-launched task inherits the workspace via context copy anyway;
        # this makes it explicit AND fixes scheduler-launched tasks, whose ambient context
        # is `local`. No-op locally (workspace is None → nullcontext).
        ws_ctx = tenancy.use_workspace(task.workspace) if task.workspace else contextlib.nullcontext()
        try:
            with ws_ctx:
                async for ev in gen_factory():
                    task.events.append(ev)
                    task.updated_at = _now_iso()
                    if ev.get("type") == "error":
                        task.error = ev.get("text")
                    # Incremental durability: a long task only saved at the end would lose
                    # its whole transcript if the process died mid-run (only the empty shell
                    # from start() survived). Flush on a time throttle so a crash costs at
                    # most the last few seconds of events, without an I/O write per token.
                    now = time.monotonic()
                    if now - last_flush >= _FLUSH_INTERVAL_SEC:
                        self._save()
                        last_flush = now
                task.status = "error" if task.error else "done"
        except asyncio.CancelledError:
            task.status = "cancelled"
            raise
        except Exception as e:  # noqa: BLE001 - surface any failure as task state
            task.status = "error"
            task.error = str(e)[:300]
        finally:
            task.updated_at = _now_iso()
            self._save()  # durable: the finished transcript survives a restart

    def start(self, goal: str, gen_factory: Callable[[], AsyncIterator[dict]], *,
              approval: str = "skip", turn_id: str | None = None,
              project_id: str | None = None, model: str = "",
              provider: str | None = None, effort: str = "High") -> Task:
        """Register a task and launch it on the running event loop."""
        task = Task(id=uuid.uuid4().hex[:12], goal=goal, title=title_of(goal),
                    approval=approval, turn_id=turn_id, project_id=project_id,
                    # Capture the ambient (non-local) workspace so the run is re-bound to it.
                    workspace=tenancy.namespace(),
                    model=model, provider=provider, effort=effort)
        self._tasks[task.id] = task
        self._save()  # record it exists before the first event lands
        task.handle = asyncio.create_task(self._run(task, gen_factory))
        return task

    def list(self) -> list[dict]:
        if tenancy.enforcing():
            return [Task.from_persisted(item).summary()
                    for item in workspace_store.list_cowork()]
        return [t.summary() for t in sorted(self._tasks.values(),
                                            key=lambda t: t.created_at, reverse=True)]

    def get(self, task_id: str) -> dict | None:
        if tenancy.enforcing():
            item = workspace_store.get_cowork(task_id)
            return Task.from_persisted(item).detail() if item else None
        t = self._tasks.get(task_id)
        return t.detail() if t else None

    def is_running(self, task_id: str) -> bool:
        """Whether a task is currently executing (used by the scheduler overlap guard)."""
        t = self._tasks.get(task_id)
        return bool(t and t.status == "running")

    def cancel_all_running(self) -> int:
        """Cancel every in-flight task (the autonomy kill-switch). Returns the count."""
        n = 0
        for t in list(self._tasks.values()):
            if t.status == "running" and t.handle is not None:
                t.handle.cancel()
                n += 1
        return n

    def cancel(self, task_id: str) -> bool:
        t = self._tasks.get(task_id)
        if (not t or not tenancy.owns(t.workspace)
                or t.status != "running" or t.handle is None):
            return False
        t.handle.cancel()
        return True

    def clear_finished(self) -> int:
        """Drop tasks that are no longer running (the 'Clear active' action). Returns
        how many were removed."""
        if tenancy.enforcing():
            finished = [item["id"] for item in workspace_store.list_cowork()
                        if item.get("status") != "running"]
            for tid in finished:
                workspace_store.delete_cowork(tid)
                task = self._tasks.get(tid)
                if task and tenancy.owns(task.workspace):
                    del self._tasks[tid]
            return len(finished)
        finished = [tid for tid, t in self._tasks.items() if t.status != "running"]
        for tid in finished:
            del self._tasks[tid]
        if finished:
            self._save()
        return len(finished)

    async def aclose(self) -> None:
        """Cancel all running tasks (shutdown), persisting their final state."""
        for t in self._tasks.values():
            if t.handle and not t.handle.done():
                t.handle.cancel()
                with contextlib.suppress(Exception):
                    await t.handle
        self._save()

    def reset_for_tests(self) -> None:
        self._tasks.clear()


manager = CoworkManager()
