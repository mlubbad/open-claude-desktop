from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime

from ocd_core import jobqueue
from ocd_core.db import engine
from ocd_core.db.models import Job


def _now():
    return datetime.now(UTC)


def test_completion_and_failure_require_current_lease_owner(db, monkeypatch):
    monkeypatch.setenv("OCD_JOB_QUEUE", "sql")
    jobqueue.reset_queue()
    queue = jobqueue.get_job_queue()
    job_id = queue.enqueue("work", {}, run_at=_now())
    claimed = queue.claim("owner", 60, now=_now())

    assert queue.complete(job_id, "intruder", claimed.lease_token) is False
    assert queue.fail(job_id, "intruder", claimed.lease_token, "forged") is False
    assert queue.complete(job_id, "owner", claimed.lease_token) is True

    with engine.session() as session:
        assert session.get(Job, job_id).status == "done"


def test_stale_lease_token_cannot_finish_reclaimed_job(db, monkeypatch):
    monkeypatch.setenv("OCD_JOB_QUEUE", "sql")
    jobqueue.reset_queue()
    queue = jobqueue.get_job_queue()
    job_id = queue.enqueue("work", {}, run_at=_now())
    first = queue.claim("worker", 1, now=_now())
    queue.reclaim_expired(now=datetime(2099, 1, 1, tzinfo=UTC))
    second = queue.claim("worker", 60, now=datetime(2099, 1, 1, 0, 0, 1, tzinfo=UTC))

    assert second.lease_token != first.lease_token
    assert queue.complete(job_id, "worker", first.lease_token) is False
    assert queue.complete(job_id, "worker", second.lease_token) is True


def test_worker_heartbeats_while_dispatch_is_running(db, monkeypatch):
    monkeypatch.setenv("OCD_JOB_QUEUE", "sql")
    jobqueue.reset_queue()
    jobqueue.clear_runners()
    queue = jobqueue.get_job_queue()
    queue.enqueue("slow", {})

    beats = []
    original = queue.heartbeat

    def spy(*args, **kwargs):
        beats.append(args)
        return original(*args, **kwargs)

    monkeypatch.setattr(queue, "heartbeat", spy)
    jobqueue.register_runner("slow", lambda _payload: time.sleep(1.2))
    ran = asyncio.run(
        jobqueue.run_worker(
            "worker", lease_seconds=1, iterations=1, poll_seconds=0
        )
    )

    assert ran == 1
    assert beats
