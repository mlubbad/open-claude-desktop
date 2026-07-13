"""Scheduled Cowork tasks (Phase 6 automations).

The schedule math (`is_due`) is pure and clock-injected; the service's store and launcher
are injectable, so the launch→advance→don't-refire lifecycle is verified without real time
or an LLM.
"""
from datetime import UTC, datetime, timedelta

from ocd_core import scheduler
from ocd_core.scheduler import Schedule, SchedulerService, ScheduleStore

NOON = datetime(2026, 7, 4, 12, 0, 0, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ---- pure is_due -----------------------------------------------------------------

def test_interval_due_when_never_run():
    s = Schedule(id="a", goal="g", kind="interval", every_seconds=60)
    assert scheduler.is_due(s, NOON) is True


def test_interval_not_due_before_interval_elapses():
    s = Schedule(id="a", goal="g", kind="interval", every_seconds=3600,
                 last_run=_iso(NOON - timedelta(minutes=10)))
    assert scheduler.is_due(s, NOON) is False


def test_interval_due_after_interval_elapses():
    s = Schedule(id="a", goal="g", kind="interval", every_seconds=600,
                 last_run=_iso(NOON - timedelta(minutes=20)))
    assert scheduler.is_due(s, NOON) is True


def test_daily_due_after_target_when_not_run_today():
    s = Schedule(id="a", goal="g", kind="daily", at="09:00",
                 last_run=_iso(NOON - timedelta(days=1)))  # ran yesterday
    assert scheduler.is_due(s, NOON) is True


def test_daily_not_due_before_target():
    s = Schedule(id="a", goal="g", kind="daily", at="18:00", last_run=None)
    assert scheduler.is_due(s, NOON) is False  # noon is before 18:00


def test_daily_not_due_when_already_run_after_target():
    s = Schedule(id="a", goal="g", kind="daily", at="09:00",
                 last_run=_iso(NOON - timedelta(minutes=30)))  # ran at 11:30, after 09:00
    assert scheduler.is_due(s, NOON) is False


def test_disabled_is_never_due():
    s = Schedule(id="a", goal="g", kind="interval", every_seconds=1, enabled=False)
    assert scheduler.is_due(s, NOON) is False


def test_describe_labels():
    assert scheduler.describe(Schedule(id="a", goal="g", every_seconds=3600)) == "every 1h"
    assert scheduler.describe(Schedule(id="a", goal="g", every_seconds=300)) == "every 5m"
    assert scheduler.describe(Schedule(id="a", goal="g", kind="daily", at="09:00")) == "daily at 09:00 UTC"


# ---- service CRUD + tick ---------------------------------------------------------

def _svc(tmp_path, launched):
    store = ScheduleStore(tmp_path / "schedules.json")
    return SchedulerService(store=store, launch=lambda s: launched.append(s.id) or "task1")


def test_add_list_remove_roundtrip(tmp_path):
    svc = _svc(tmp_path, [])
    created = svc.add(goal="Digest the news", kind="interval", every_seconds=3600)
    assert created["cadence"] == "every 1h"
    listed = svc.list()
    assert len(listed) == 1 and listed[0]["title"] == "Digest the news"
    assert svc.remove(created["id"]) is True
    assert svc.list() == []
    assert svc.remove("gone") is False


def test_set_enabled_persists(tmp_path):
    svc = _svc(tmp_path, [])
    created = svc.add(goal="g", kind="interval", every_seconds=60)
    off = svc.set_enabled(created["id"], False)
    assert off["enabled"] is False
    assert svc.list()[0]["enabled"] is False
    assert svc.set_enabled("missing", True) is None


def test_tick_launches_due_and_advances_last_run(tmp_path):
    launched: list[str] = []
    svc = _svc(tmp_path, launched)
    # Seed a schedule that is already due (ran 20 minutes ago, fires every 10).
    svc.store.save([Schedule(id="s1", goal="g", kind="interval", every_seconds=600,
                             last_run=_iso(NOON - timedelta(minutes=20)))])
    fired = svc.tick(now=NOON)
    assert fired == ["s1"]
    assert launched == ["s1"]
    # last_run advanced to NOON, so an immediate second tick does nothing.
    assert svc.tick(now=NOON) == []
    assert launched == ["s1"]


def test_tick_skips_not_due_and_disabled(tmp_path):
    launched: list[str] = []
    svc = _svc(tmp_path, launched)
    svc.store.save([
        Schedule(id="soon", goal="g", kind="interval", every_seconds=3600,
                 last_run=_iso(NOON - timedelta(minutes=1))),         # not due yet
        Schedule(id="off", goal="g", kind="interval", every_seconds=1, enabled=False,
                 last_run=_iso(NOON - timedelta(days=1))),            # disabled
    ])
    assert svc.tick(now=NOON) == []
    assert launched == []


def test_tick_does_not_advance_when_launch_fails(tmp_path):
    def boom(_s):
        raise RuntimeError("no loop")
    store = ScheduleStore(tmp_path / "schedules.json")
    svc = SchedulerService(store=store, launch=boom)
    svc.store.save([Schedule(id="s1", goal="g", kind="interval", every_seconds=1,
                             last_run=_iso(NOON - timedelta(minutes=5)))])
    assert svc.tick(now=NOON) == []          # launch failed → not counted
    # last_run unchanged, so it's still due (will retry next tick).
    assert scheduler.is_due(svc.store.load()[0], NOON) is True


def test_tick_skips_when_previous_run_still_active(tmp_path, monkeypatch):
    """Overlap guard: a schedule whose prior launch is still running must NOT stack a
    second copy; once the prior finishes, the next tick launches again."""
    from ocd_core import cowork
    launched: list[str] = []
    svc = _svc(tmp_path, launched)            # launch returns the task id "task1"
    svc.store.save([Schedule(id="s1", goal="g", kind="interval", every_seconds=600,
                             last_run=_iso(NOON - timedelta(minutes=20)))])
    assert svc.tick(now=NOON) == ["s1"]       # first launch
    assert launched == ["s1"]

    later = NOON + timedelta(minutes=20)      # due again by interval
    monkeypatch.setattr(cowork.manager, "is_running", lambda tid: tid == "task1")
    assert svc.tick(now=later) == []          # prior still running → skipped
    assert launched == ["s1"]                 # no second launch

    monkeypatch.setattr(cowork.manager, "is_running", lambda tid: False)
    assert svc.tick(now=later) == ["s1"]      # prior finished → relaunches
    assert launched == ["s1", "s1"]


def test_tick_skips_all_when_autonomy_paused(tmp_path, monkeypatch):
    """Global kill-switch: while autonomy is paused NO scheduled automation fires, and
    last_run is untouched so every due schedule resumes once it's unpaused."""
    from ocd_core import settings as settings_mod
    monkeypatch.setattr(settings_mod, "get_settings", lambda: {"autonomy_paused": True})
    launched: list[str] = []
    svc = _svc(tmp_path, launched)
    svc.store.save([Schedule(id="s1", goal="g", kind="interval", every_seconds=1,
                             last_run=_iso(NOON - timedelta(minutes=5)))])
    assert svc.tick(now=NOON) == []
    assert launched == []
    monkeypatch.setattr(settings_mod, "get_settings", lambda: {"autonomy_paused": False})
    assert svc.tick(now=NOON) == ["s1"]     # unpaused → the still-due schedule fires


def test_tick_overlap_guard_can_be_disabled(tmp_path, monkeypatch):
    """OCD_SCHEDULER_SKIP_OVERLAP off → a due schedule fires even if the prior is live."""
    from ocd_core import config, cowork
    monkeypatch.setattr(config, "SCHEDULER_SKIP_OVERLAP", False)
    launched: list[str] = []
    svc = _svc(tmp_path, launched)
    svc.store.save([Schedule(id="s1", goal="g", kind="interval", every_seconds=600,
                             last_run=_iso(NOON - timedelta(minutes=20)))])
    assert svc.tick(now=NOON) == ["s1"]
    monkeypatch.setattr(cowork.manager, "is_running", lambda tid: True)  # prior "live"
    assert svc.tick(now=NOON + timedelta(minutes=20)) == ["s1"]          # fires anyway
    assert launched == ["s1", "s1"]
