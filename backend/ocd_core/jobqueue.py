"""Durable job queue for background work (hosted-SaaS slice 4c).

OFF by default. `OCD_JOB_QUEUE` unset or ``inprocess`` selects `InProcessJobQueue`,
which runs an enqueued job IMMEDIATELY via its registered runner — exactly the
pre-queue behavior, so the packaged desktop and a single-node server are
unchanged. Flip ``OCD_JOB_QUEUE=sql`` for a durable, DB-backed queue: enqueued
jobs become rows in the shared database (SQLite locally, Postgres for real
multi-node), and a `run_worker()` on any node atomically CLAIMS a due job under a
time-boxed LEASE, dispatches it, and marks it done. A worker that dies mid-job
lets the lease expire; `reclaim_expired()` returns the job to the queue so
another worker picks it up (at-least-once dispatch). `dedup_key` gives idempotent
enqueue, so two nodes racing to schedule the same occurrence produce one job.

The queue moves *serializable job specs* (a kind + a JSON payload), not live
closures — so a job can be built on one node and run on another. Each `kind` has
a registered runner (`register_runner`) that rebuilds and performs the work from
the payload; the scheduler registers ``run_schedule``.
"""
from __future__ import annotations

import contextlib
import os
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import update
from sqlmodel import select

from . import tenancy
from .db import engine
from .db.models import Job


def _utcnow() -> datetime:
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
#  Runner registry — kind -> "how to perform this job from its payload"
# --------------------------------------------------------------------------- #
_RUNNERS: dict[str, Callable[[dict], object]] = {}


def register_runner(kind: str, fn: Callable[[dict], object]) -> None:
    """Register the runner for a job ``kind``. Idempotent (last registration wins)."""
    _RUNNERS[kind] = fn


def clear_runners() -> None:
    """Test helper: drop all registered runners."""
    _RUNNERS.clear()


def dispatch(kind: str, payload: dict, workspace: str | None = None) -> object:
    """Run a job's registered runner, re-binding the owning workspace for the call
    (a background worker runs outside any request, so the tenant is carried explicitly)."""
    fn = _RUNNERS.get(kind)
    if fn is None:
        raise KeyError(f"no runner registered for job kind {kind!r}")
    ctx = tenancy.use_workspace(workspace) if workspace else contextlib.nullcontext()
    with ctx:
        return fn(payload or {})


@dataclass
class ClaimedJob:
    id: str
    kind: str
    payload: dict
    workspace: str | None
    attempts: int
    max_attempts: int
    lease_token: str


# --------------------------------------------------------------------------- #
#  Interface
# --------------------------------------------------------------------------- #
class JobQueue(ABC):
    is_durable: bool = False

    @abstractmethod
    def enqueue(self, kind: str, payload: dict, *, dedup_key: str | None = None,
                run_at: datetime | None = None, workspace: str | None = None,
                max_attempts: int = 3) -> str | None:
        """Submit a job. Returns its id, or None when a ``dedup_key`` is already queued
        (idempotent no-op) or the backend ran it inline."""

    @abstractmethod
    def claim(self, worker_id: str, lease_seconds: int,
              now: datetime | None = None) -> ClaimedJob | None:
        """Atomically take one due job under a lease. None when nothing is ready."""

    @abstractmethod
    def heartbeat(self, job_id: str, worker_id: str, lease_token: str, lease_seconds: int,
                  now: datetime | None = None) -> bool:
        """Extend the lease on a job this worker still owns. False if it lost ownership."""

    @abstractmethod
    def complete(self, job_id: str, worker_id: str, lease_token: str) -> bool:
        """Finish only the running attempt holding the current fenced lease."""

    @abstractmethod
    def fail(self, job_id: str, worker_id: str, lease_token: str, error: str, *,
             retry_at: datetime | None = None, now: datetime | None = None) -> bool:
        """Record a failure. Requeues (until max_attempts) when ``retry_at`` is given,
        else marks the job failed."""

    @abstractmethod
    def reclaim_expired(self, now: datetime | None = None) -> int:
        """Return lease-expired ``running`` jobs to the queue (or fail the exhausted
        ones). Returns how many rows were touched."""

    @abstractmethod
    def pending_count(self) -> int: ...


# --------------------------------------------------------------------------- #
#  In-process (default) — run now, no persistence beyond the runner's own
# --------------------------------------------------------------------------- #
class InProcessJobQueue(JobQueue):
    is_durable = False

    def enqueue(self, kind, payload, *, dedup_key=None, run_at=None, workspace=None,
                max_attempts=3):
        # Run immediately via the registered runner — the pre-queue inline behavior.
        dispatch(kind, payload or {}, workspace if workspace is not None
                 else tenancy.namespace())
        return None

    def claim(self, worker_id, lease_seconds, now=None):
        return None

    def heartbeat(self, job_id, worker_id, lease_token, lease_seconds, now=None):
        return False

    def complete(self, job_id, worker_id, lease_token):
        return False

    def fail(self, job_id, worker_id, lease_token, error, *, retry_at=None, now=None):
        return False

    def reclaim_expired(self, now=None):
        return 0

    def pending_count(self):
        return 0


# --------------------------------------------------------------------------- #
#  SQL (opt-in) — durable, claim/lease/heartbeat/reclaim on the shared DB
# --------------------------------------------------------------------------- #
class SqlJobQueue(JobQueue):
    is_durable = True

    def enqueue(self, kind, payload, *, dedup_key=None, run_at=None, workspace=None,
                max_attempts=3):
        from sqlalchemy.exc import IntegrityError
        job = Job(id=uuid.uuid4().hex, kind=kind, payload=payload or {},
                  dedup_key=dedup_key, run_at=run_at or _utcnow(),
                  max_attempts=max_attempts,
                  workspace_id=workspace if workspace is not None else tenancy.namespace())
        try:
            with engine.session() as s:
                s.add(job)
            return job.id
        except IntegrityError:
            # A UNIQUE dedup_key already queued this occurrence — idempotent no-op, so two
            # nodes racing to enqueue the same scheduled occurrence produce a single job.
            return None

    def claim(self, worker_id, lease_seconds, now=None):
        now = now or _utcnow()
        lease = now + timedelta(seconds=lease_seconds)
        lease_token = uuid.uuid4().hex
        with engine.session() as s:
            # Oldest ready job first. The claim is made atomic by the conditional UPDATE
            # below (WHERE status='queued'), so even if two workers select the same row,
            # only one UPDATE takes effect; the loser simply gets None and polls again.
            row = s.exec(
                select(Job).where(Job.status == "queued", Job.run_at <= now)
                .order_by(Job.run_at).limit(1)).first()
            if row is None:
                return None
            res = s.exec(
                update(Job).where(Job.id == row.id, Job.status == "queued").values(
                    status="running", worker_id=worker_id, lease_expires_at=lease,
                    lease_token=lease_token,
                    attempts=Job.attempts + 1, updated_at=now))
            if res.rowcount != 1:
                return None  # lost the race
            claimed = s.get(Job, row.id)
            return ClaimedJob(id=claimed.id, kind=claimed.kind, payload=dict(claimed.payload or {}),
                              workspace=claimed.workspace_id, attempts=claimed.attempts,
                              max_attempts=claimed.max_attempts,
                              lease_token=claimed.lease_token)

    def heartbeat(self, job_id, worker_id, lease_token, lease_seconds, now=None):
        now = now or _utcnow()
        lease = now + timedelta(seconds=lease_seconds)
        with engine.session() as s:
            res = s.exec(
                update(Job).where(Job.id == job_id, Job.worker_id == worker_id,
                                  Job.lease_token == lease_token,
                                  Job.status == "running",
                                  Job.lease_expires_at >= now).values(
                    lease_expires_at=lease, updated_at=now))
            return res.rowcount == 1

    def complete(self, job_id, worker_id, lease_token):
        now = _utcnow()
        with engine.session() as s:
            result = s.exec(
                update(Job).where(
                    Job.id == job_id,
                    Job.status == "running",
                    Job.worker_id == worker_id,
                    Job.lease_token == lease_token,
                ).values(
                    status="done",
                    worker_id=None,
                    lease_token=None,
                    lease_expires_at=None,
                    updated_at=now,
                )
            )
            return result.rowcount == 1

    def fail(self, job_id, worker_id, lease_token, error, *, retry_at=None, now=None):
        now = now or _utcnow()
        with engine.session() as s:
            job = s.exec(
                select(Job).where(
                    Job.id == job_id,
                    Job.status == "running",
                    Job.worker_id == worker_id,
                    Job.lease_token == lease_token,
                )
            ).first()
            if job is None:
                return False
            requeue = retry_at is not None and job.attempts < job.max_attempts
            if requeue:
                job.status = "queued"
                job.run_at = retry_at
                job.worker_id = None
                job.lease_token = None
                job.lease_expires_at = None
            else:
                job.status = "failed"
                job.worker_id = None
                job.lease_token = None
                job.lease_expires_at = None
            job.last_error = (error or "")[:1000]
            job.updated_at = now
            s.add(job)
            return True

    def reclaim_expired(self, now=None):
        now = now or _utcnow()
        touched = 0
        with engine.session() as s:
            # Exhausted (a worker died on the last allowed attempt) → fail, don't loop.
            res_fail = s.exec(
                update(Job).where(Job.status == "running", Job.lease_expires_at < now,
                                  Job.attempts >= Job.max_attempts).values(
                    status="failed", worker_id=None, lease_expires_at=None,
                    lease_token=None,
                    last_error="lease expired (worker presumed dead); attempts exhausted",
                    updated_at=now))
            # Otherwise return to the queue for another worker to claim.
            res_requeue = s.exec(
                update(Job).where(Job.status == "running", Job.lease_expires_at < now).values(
                    status="queued", worker_id=None, lease_token=None,
                    lease_expires_at=None, updated_at=now))
            touched = (res_fail.rowcount or 0) + (res_requeue.rowcount or 0)
        return touched

    def pending_count(self):
        from sqlmodel import func, select
        with engine.session() as s:
            return s.exec(select(func.count()).select_from(Job)
                          .where(Job.status == "queued")).one()


# --------------------------------------------------------------------------- #
#  Factory
# --------------------------------------------------------------------------- #
_queue: JobQueue | None = None
_queue_backend: str | None = None


def backend_name() -> str:
    return (os.getenv("OCD_JOB_QUEUE") or "inprocess").strip().lower()


def enabled() -> bool:
    """True when a durable queue backend is selected (background jobs are persisted)."""
    return backend_name() in ("sql", "db", "database")


def get_job_queue() -> JobQueue:
    global _queue, _queue_backend
    name = backend_name()
    if _queue is None or _queue_backend != name:
        _queue = SqlJobQueue() if name in ("sql", "db", "database") else InProcessJobQueue()
        _queue_backend = name
    return _queue


def reset_queue() -> None:
    """Drop the cached queue (tests / a runtime backend switch)."""
    global _queue, _queue_backend
    _queue = None
    _queue_backend = None


# --------------------------------------------------------------------------- #
#  Worker runtime (durable backends only)
# --------------------------------------------------------------------------- #
async def run_worker(worker_id: str | None = None, *, lease_seconds: int = 120,
                     poll_seconds: float = 2.0, iterations: int | None = None) -> int:
    """Claim-and-dispatch loop for a durable queue. Returns the number of jobs it ran.

    No-op for the in-process backend (jobs run at enqueue). ``iterations`` bounds the
    loop for tests; None runs forever. Reclaims lease-expired jobs each pass so a dead
    node's work is retried here."""
    import asyncio
    q = get_job_queue()
    if not q.is_durable:
        return 0
    worker_id = worker_id or uuid.uuid4().hex[:12]
    ran = 0
    n = 0
    while iterations is None or n < iterations:
        n += 1
        with contextlib.suppress(Exception):
            q.reclaim_expired()
        job = None
        with contextlib.suppress(Exception):
            job = q.claim(worker_id, lease_seconds)
        if job is None:
            if iterations is not None:
                continue  # tests: don't sleep, just advance
            await asyncio.sleep(poll_seconds)
            continue
        stop_heartbeat = asyncio.Event()
        lost_lease = False

        # Bind the per-iteration job/event into the closure (B023): the task is
        # started and stopped within this iteration, but late-binding a loop
        # variable is one refactor away from heartbeating the wrong job.
        async def _heartbeat(job=job, stop_heartbeat=stop_heartbeat) -> None:
            nonlocal lost_lease
            interval = max(0.01, min(float(lease_seconds) / 3, 30.0))
            while not stop_heartbeat.is_set():
                try:
                    await asyncio.wait_for(stop_heartbeat.wait(), timeout=interval)
                    return
                except TimeoutError:
                    pass
                owned = await asyncio.to_thread(
                    q.heartbeat,
                    job.id,
                    worker_id,
                    job.lease_token,
                    lease_seconds,
                )
                if not owned:
                    lost_lease = True
                    return

        heartbeat_task = asyncio.create_task(_heartbeat())
        try:
            await asyncio.to_thread(dispatch, job.kind, job.payload, job.workspace)
            if not lost_lease and q.complete(job.id, worker_id, job.lease_token):
                ran += 1
        except Exception as e:  # noqa: BLE001 - one bad job must not kill the worker
            # Back off then requeue (until attempts are exhausted, when fail() gives up).
            q.fail(
                job.id,
                worker_id,
                job.lease_token,
                str(e),
                retry_at=_utcnow() + timedelta(seconds=30),
            )
        finally:
            stop_heartbeat.set()
            with contextlib.suppress(Exception):
                await heartbeat_task
    return ran
