"""Durable job queue (hosted-SaaS slice 4c).

The SqlJobQueue is exercised against a fresh in-memory SQLite DB (the `db`
fixture); the in-process default and the scheduler wiring are covered too. Clocks
are injected so lease/reclaim behavior is deterministic without waiting.
"""
from datetime import UTC, datetime, timedelta

import pytest
from ocd_core import jobqueue, tenancy


@pytest.fixture(autouse=True)
def _reset():
    jobqueue.reset_queue()
    jobqueue.clear_runners()
    yield
    jobqueue.reset_queue()
    jobqueue.clear_runners()


def _t(offset=0):
    return datetime(2026, 7, 15, 12, 0, 0, tzinfo=UTC) + timedelta(seconds=offset)


# --------------------------------------------------------------------------- #
#  Factory
# --------------------------------------------------------------------------- #
def test_factory_defaults_to_inprocess(monkeypatch):
    monkeypatch.delenv("OCD_JOB_QUEUE", raising=False)
    assert jobqueue.backend_name() == "inprocess"
    assert jobqueue.enabled() is False
    assert isinstance(jobqueue.get_job_queue(), jobqueue.InProcessJobQueue)


def test_factory_sql_is_durable(monkeypatch):
    monkeypatch.setenv("OCD_JOB_QUEUE", "sql")
    assert jobqueue.enabled() is True
    q = jobqueue.get_job_queue()
    assert isinstance(q, jobqueue.SqlJobQueue) and q.is_durable is True


# --------------------------------------------------------------------------- #
#  In-process backend runs enqueued work immediately (pre-queue behavior)
# --------------------------------------------------------------------------- #
def test_inprocess_runs_at_enqueue(monkeypatch):
    monkeypatch.delenv("OCD_JOB_QUEUE", raising=False)
    ran = []
    jobqueue.register_runner("echo", lambda p: ran.append(p["v"]))
    jid = jobqueue.get_job_queue().enqueue("echo", {"v": 42})
    assert jid is None            # nothing persisted
    assert ran == [42]            # it ran inline


# --------------------------------------------------------------------------- #
#  SQL backend: enqueue → claim → complete
# --------------------------------------------------------------------------- #
def test_sql_enqueue_claim_complete(db, monkeypatch):
    monkeypatch.setenv("OCD_JOB_QUEUE", "sql")
    q = jobqueue.get_job_queue()
    jid = q.enqueue("echo", {"v": 1}, run_at=_t())
    assert jid and q.pending_count() == 1

    job = q.claim("worker-1", lease_seconds=60, now=_t())
    assert job is not None and job.kind == "echo" and job.payload == {"v": 1}
    assert job.attempts == 1
    assert q.pending_count() == 0            # no longer queued
    # A second worker finds nothing to claim.
    assert q.claim("worker-2", lease_seconds=60, now=_t()) is None
    assert q.complete(job.id, "worker-1", job.lease_token) is True


def test_sql_run_at_delays_claim(db, monkeypatch):
    monkeypatch.setenv("OCD_JOB_QUEUE", "sql")
    q = jobqueue.get_job_queue()
    q.enqueue("echo", {}, run_at=_t(100))    # not ready until t+100
    assert q.claim("w", 60, now=_t(10)) is None
    assert q.claim("w", 60, now=_t(200)) is not None


def test_sql_dedup_key_is_idempotent(db, monkeypatch):
    monkeypatch.setenv("OCD_JOB_QUEUE", "sql")
    q = jobqueue.get_job_queue()
    first = q.enqueue("echo", {"n": 1}, dedup_key="occ-A")
    second = q.enqueue("echo", {"n": 2}, dedup_key="occ-A")  # same occurrence
    assert first and second is None          # only one job created
    assert q.pending_count() == 1


def test_sql_reclaim_expired_lease_requeues(db, monkeypatch):
    monkeypatch.setenv("OCD_JOB_QUEUE", "sql")
    q = jobqueue.get_job_queue()
    q.enqueue("echo", {}, run_at=_t())
    job = q.claim("dead-worker", lease_seconds=30, now=_t())
    assert job is not None and q.pending_count() == 0
    # Before the lease expires: nothing to reclaim.
    assert q.reclaim_expired(now=_t(10)) == 0
    # After it expires (worker presumed dead): the job returns to the queue.
    assert q.reclaim_expired(now=_t(60)) == 1
    assert q.pending_count() == 1
    again = q.claim("live-worker", lease_seconds=30, now=_t(61))
    assert again is not None and again.attempts == 2   # attempt count carried forward


def test_sql_reclaim_fails_when_attempts_exhausted(db, monkeypatch):
    monkeypatch.setenv("OCD_JOB_QUEUE", "sql")
    q = jobqueue.get_job_queue()
    q.enqueue("echo", {}, max_attempts=1, run_at=_t())
    q.claim("dead", lease_seconds=30, now=_t())          # attempts -> 1 (== max)
    # Lease expires with attempts exhausted → the job is failed, not requeued forever.
    assert q.reclaim_expired(now=_t(60)) == 1
    assert q.pending_count() == 0


def test_sql_heartbeat_extends_only_for_owner(db, monkeypatch):
    monkeypatch.setenv("OCD_JOB_QUEUE", "sql")
    q = jobqueue.get_job_queue()
    q.enqueue("echo", {}, run_at=_t())
    job = q.claim("owner", lease_seconds=30, now=_t())
    assert q.heartbeat(job.id, "owner", job.lease_token, 30, now=_t(20)) is True
    assert q.heartbeat(
        job.id, "someone-else", job.lease_token, 30, now=_t(20)
    ) is False
    # With the lease pushed out to t+50, it is NOT reclaimable at t+40.
    assert q.reclaim_expired(now=_t(40)) == 0


def test_sql_fail_without_retry_marks_failed(db, monkeypatch):
    monkeypatch.setenv("OCD_JOB_QUEUE", "sql")
    q = jobqueue.get_job_queue()
    q.enqueue("echo", {}, run_at=_t())
    job = q.claim("w", 30, now=_t())
    q.fail(job.id, "w", job.lease_token, "boom")  # no retry_at → terminal
    assert q.pending_count() == 0
    assert q.reclaim_expired(now=_t(999)) == 0  # failed jobs aren't reclaimed


def test_sql_fail_with_retry_requeues(db, monkeypatch):
    monkeypatch.setenv("OCD_JOB_QUEUE", "sql")
    q = jobqueue.get_job_queue()
    q.enqueue("echo", {}, run_at=_t())
    job = q.claim("w", 30, now=_t())
    q.fail(job.id, "w", job.lease_token, "transient", retry_at=_t(5))
    assert q.pending_count() == 1
    assert q.claim("w", 30, now=_t(10)) is not None


# --------------------------------------------------------------------------- #
#  Worker runtime
# --------------------------------------------------------------------------- #
def test_worker_claims_and_dispatches(db, monkeypatch):
    import asyncio
    monkeypatch.setenv("OCD_JOB_QUEUE", "sql")
    seen = []
    jobqueue.register_runner("echo", lambda p: seen.append(p["v"]))
    q = jobqueue.get_job_queue()
    q.enqueue("echo", {"v": "a"})
    q.enqueue("echo", {"v": "b"})
    ran = asyncio.run(jobqueue.run_worker("w1", iterations=3, poll_seconds=0))
    assert ran == 2 and sorted(seen) == ["a", "b"]
    assert q.pending_count() == 0


def test_worker_binds_job_workspace(db, monkeypatch):
    import asyncio
    monkeypatch.setenv("OCD_JOB_QUEUE", "sql")
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    seen = []
    jobqueue.register_runner("who", lambda p: seen.append(tenancy.current_workspace()))
    q = jobqueue.get_job_queue()
    q.enqueue("who", {}, workspace="wsX")
    asyncio.run(jobqueue.run_worker("w1", iterations=1, poll_seconds=0))
    assert seen == ["wsX"]     # the worker ran the job AS its owning tenant


# --------------------------------------------------------------------------- #
#  Scheduler wiring: default launches inline; durable enqueues a job
# --------------------------------------------------------------------------- #
def test_scheduler_inline_by_default(monkeypatch):
    monkeypatch.delenv("OCD_JOB_QUEUE", raising=False)
    from ocd_core import scheduler
    launched = []
    monkeypatch.setattr(scheduler, "default_launch", lambda s: launched.append(s.id) or "task-1")
    s = scheduler.Schedule(id="sch1", goal="do it")
    assert scheduler._dispatch_launch(s) == "task-1"
    assert launched == ["sch1"]


def test_scheduler_durable_enqueues_job(db, monkeypatch):
    monkeypatch.setenv("OCD_JOB_QUEUE", "sql")
    from ocd_core import scheduler
    # In durable mode the launcher enqueues instead of launching inline.
    monkeypatch.setattr(scheduler, "default_launch",
                        lambda s: (_ for _ in ()).throw(AssertionError("must not launch inline")))
    s = scheduler.Schedule(id="sch2", goal="later", last_run="2026-07-15T12:00:00+00:00")
    jid = scheduler._dispatch_launch(s)
    assert jid                                   # a job id came back
    q = jobqueue.get_job_queue()
    assert q.pending_count() == 1
    # The run_schedule runner is registered and reloads + launches the schedule.
    job = q.claim("w", 60, now=_t(10**9))
    assert job.kind == "run_schedule" and job.payload == {"schedule_id": "sch2"}
