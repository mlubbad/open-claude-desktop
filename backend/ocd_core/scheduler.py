"""Scheduled Cowork tasks ("automations") — run a goal on a recurring schedule.

A Schedule is either an INTERVAL ("every N seconds") or a DAILY time ("HH:MM", UTC).
The service TICKS periodically; on each tick every due-and-enabled schedule launches a
Cowork background task and its ``last_run`` advances. The schedule math (`is_due`) is
pure and clock-injected, and both the store and the launcher are injectable, so the whole
thing is verifiable without waiting on wall-clock time or an LLM.
"""
from __future__ import annotations

import contextlib
import json
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from . import agent, config, cowork, jsonstore, opik_tracing


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Schedule:
    id: str
    goal: str
    kind: str = "interval"           # "interval" | "daily"
    every_seconds: int | None = None
    at: str | None = None            # "HH:MM" (UTC) for daily
    enabled: bool = True
    last_run: str | None = None      # ISO timestamp of the last launch
    model: str = ""
    provider: str | None = None
    effort: str = "High"
    project_id: str | None = None
    title: str = ""


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    with contextlib.suppress(ValueError):
        return datetime.fromisoformat(ts)
    return None


def is_due(s: Schedule, now: datetime) -> bool:
    """Whether an enabled schedule should launch at `now` given its last_run."""
    if not s.enabled:
        return False
    last = _parse(s.last_run)
    if s.kind == "interval":
        if not s.every_seconds or s.every_seconds <= 0:
            return False
        if last is None:
            return True
        return (now - last).total_seconds() >= s.every_seconds
    if s.kind == "daily":
        try:
            hh, mm = (int(x) for x in (s.at or "").split(":"))
            target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        except ValueError:
            return False
        if now < target:
            return False
        return last is None or last < target
    return False


def describe(s: Schedule) -> str:
    """A short human label for the cadence (used by the UI)."""
    if s.kind == "interval" and s.every_seconds:
        n = s.every_seconds
        if n % 3600 == 0:
            return f"every {n // 3600}h"
        if n % 60 == 0:
            return f"every {n // 60}m"
        return f"every {n}s"
    if s.kind == "daily" and s.at:
        return f"daily at {s.at} UTC"
    return "—"


class ScheduleStore:
    """JSON-file persistence for the schedule list."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else Path(config.REPO_ROOT) / "schedules.json"

    def load(self) -> list[Schedule]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        fields = set(Schedule.__dataclass_fields__)
        out = []
        for d in raw if isinstance(raw, list) else []:
            if isinstance(d, dict) and d.get("id"):
                out.append(Schedule(**{k: v for k, v in d.items() if k in fields}))
        return out

    def save(self, schedules: list[Schedule]) -> None:
        # Atomic write (temp + os.replace): a crash mid-write must not truncate
        # schedules.json — load() fails soft to [], which would silently erase
        # every automation the user configured.
        with contextlib.suppress(OSError):
            jsonstore.save_json(self.path, [asdict(s) for s in schedules])


def default_launch(s: Schedule) -> str:
    """Launch a scheduled goal as an autonomous Cowork task (returns the task id).

    Scheduled runs are unattended by definition — no one is watching to answer a
    prompt — so they run at permission_mode=auto WITHOUT the destructive local tools
    (code_execution/bash/text_editor). With the HITL gate off, those would let any
    prompt-injected page/doc/MCP output run code on the user's machine unsupervised;
    the read/browse/orchestrate set stays available so automations can still work."""
    model = s.model or config.AGENT_MODEL
    tools = agent.background_tool_flags(gated=False)

    def gen_factory():
        # Opik tap (opt-in): scheduled runs were the one turn source left invisible
        # in traces — chat and Cowork are already wrapped at their routes.
        return opik_tracing.traced(
            agent.run_turn(
                s.goal, [], s.project_id, model,
                effort=s.effort, provider=s.provider, permission_mode="auto",
                **tools),
            goal=s.goal, model=model, provider=s.provider, effort=s.effort,
            tags=["scheduled"])
    return cowork.manager.start(
        s.goal, gen_factory, approval="skip", project_id=s.project_id,
        model=model, provider=s.provider, effort=s.effort).id


class SchedulerService:
    def __init__(self, store: ScheduleStore | None = None,
                 launch: Callable[[Schedule], str] = default_launch) -> None:
        self.store = store or ScheduleStore()
        self.launch = launch
        # schedule id -> the task id of its most recent launch, for the overlap guard.
        self._last_task: dict[str, str] = {}

    def _still_running(self, sid: str) -> bool:
        """Whether this schedule's previous launch is still executing."""
        tid = self._last_task.get(sid)
        return bool(tid and cowork.manager.is_running(tid))

    def list(self) -> list[dict]:
        return [{**asdict(s), "cadence": describe(s)} for s in self.store.load()]

    def add(self, goal: str, kind: str, every_seconds: int | None = None,
            at: str | None = None, model: str = "", provider: str | None = None,
            effort: str = "High", project_id: str | None = None) -> dict:
        items = self.store.load()
        s = Schedule(id=uuid.uuid4().hex[:12], goal=goal, kind=kind,
                     every_seconds=every_seconds, at=at, model=model, provider=provider,
                     effort=effort, project_id=project_id, title=cowork.title_of(goal),
                     # Stamp last_run at creation so a new schedule waits for its next
                     # occurrence instead of firing the instant it's added.
                     last_run=_now().isoformat())
        items.append(s)
        self.store.save(items)
        return {**asdict(s), "cadence": describe(s)}

    def remove(self, sid: str) -> bool:
        items = self.store.load()
        kept = [s for s in items if s.id != sid]
        self.store.save(kept)
        return len(kept) < len(items)

    def set_enabled(self, sid: str, enabled: bool) -> dict | None:
        items = self.store.load()
        found = None
        for s in items:
            if s.id == sid:
                s.enabled = bool(enabled)
                found = s
        if found:
            self.store.save(items)
            return {**asdict(found), "cadence": describe(found)}
        return None

    def tick(self, now: datetime | None = None) -> list[str]:
        """Launch every due schedule; advance last_run for the ones that launched."""
        now = now or _now()
        items = self.store.load()
        launched: list[str] = []
        for s in items:
            if not is_due(s, now):
                continue
            # Overlap guard: don't stack a second copy of an automation whose previous
            # run is still going (a slow task on a short interval would otherwise pile up
            # and multiply spend). last_run is left as-is so it relaunches the moment the
            # prior run finishes, rather than skipping the whole occurrence.
            if config.SCHEDULER_SKIP_OVERLAP and self._still_running(s.id):
                continue
            try:
                tid = self.launch(s)
            except Exception:  # noqa: BLE001 - a failed launch is retried next tick
                continue
            if tid:
                self._last_task[s.id] = tid
            s.last_run = now.isoformat()
            launched.append(s.id)
        if launched:
            self.store.save(items)
        return launched


service = SchedulerService()


async def run_loop(svc: SchedulerService | None = None, interval_seconds: int = 30) -> None:
    """Background ticker: sleep first (so startup never fires a task), then tick forever."""
    import asyncio
    svc = svc or service
    while True:
        await asyncio.sleep(interval_seconds)
        with contextlib.suppress(Exception):
            svc.tick()
