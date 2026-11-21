import json
import logging

from ocd_core import observability as obs


def test_rate_limit_sliding_window():
    rl = obs.RateLimiter(limit=2, window_sec=60)
    clock = [1000.0]

    def now():
        return clock[0]
    assert rl.check("u1", now=now) is True   # 1
    assert rl.check("u1", now=now) is True   # 2
    assert rl.check("u1", now=now) is False  # blocked
    clock[0] += 61                           # window slides
    assert rl.check("u1", now=now) is True
    # isolation between users
    assert rl.check("u2", now=now) is True


def test_audit_writes_jsonl(tmp_path):
    log = tmp_path / "audit.jsonl"
    a = obs.Audit(path=str(log), max_bytes=10_000, backups=1)
    a.write({"event": "x", "user": "u1"})
    line = log.read_text(encoding="utf-8").strip().splitlines()[-1]
    rec = json.loads(line)
    assert rec["event"] == "x" and rec["user"] == "u1" and "ts" in rec


def test_observe_emits_json(caplog):
    # observe() emits via the "ocd_agent" stderr logger. capsys can't reliably
    # capture logging.StreamHandler output (the handler binds sys.stderr at
    # construction, before capsys swaps it), so we assert on the propagated
    # log record via caplog instead -- the production behavior (emit to stderr)
    # is unchanged.
    with caplog.at_level(logging.INFO, logger="ocd_agent"):
        obs.observe("hello", n=1)
    msg = caplog.records[-1].getMessage()
    assert '"event": "hello"' in msg and '"n": 1' in msg
