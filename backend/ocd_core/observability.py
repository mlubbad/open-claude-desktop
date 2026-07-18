"""Structured logging, rotating audit trail, and rate limiting.

Salvaged from the pre-refactor app.py and decoupled from Chainlit (#1, #3).

Two distinct systems with clear separation (parity with app.py):
  - observe(): real-time structured JSON to stderr (debugging / monitoring)
  - Audit:     persistent append-only JSONL trail (compliance / forensics)
Plus a thread-safe sliding-window RateLimiter. All three are UI-agnostic:
callers pass ``user_id`` explicitly rather than reaching into a UI session.
"""
import json
import logging
import logging.handlers
import os
import sys
import threading
import time
from datetime import UTC, datetime

from . import config

# --------------------------------------------------------------------------- #
#  observe -- structured JSON to stderr (mirrors app.py._observe)
# --------------------------------------------------------------------------- #
_logger = logging.getLogger("ocd_agent")
if not _logger.handlers:
    _logger.setLevel(logging.INFO)
    _sh = logging.StreamHandler()  # defaults to sys.stderr, like app.py
    _sh.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_sh)


def observe(event: str, **fields):
    """Emit a structured log record to stderr. Non-blocking, best-effort."""
    record = {"event": event, "ts": datetime.now(UTC).isoformat(), **fields}
    _logger.info(json.dumps(record, default=str))


# --------------------------------------------------------------------------- #
#  Audit -- rotating append-only JSONL trail (mirrors app.py.audit + handler)
# --------------------------------------------------------------------------- #
class Audit:
    """Append events to a rotating JSONL audit trail. Thread-safe via the
    logging handler's internal lock. Best-effort: never raises on write."""

    def __init__(self, path=None, max_bytes=None, backups=None):
        path = path or config.AUDIT_LOG
        # Per-path logger so distinct Audit targets don't share a handler.
        self._logger = logging.getLogger(f"ocd_audit.{path}")
        self._logger.setLevel(logging.INFO)
        self._logger.propagate = False
        if not self._logger.handlers:
            try:
                os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
                fh = logging.handlers.RotatingFileHandler(
                    path,
                    maxBytes=max_bytes if max_bytes is not None else config.AUDIT_LOG_MAX_BYTES,
                    backupCount=backups if backups is not None else config.AUDIT_LOG_BACKUPS,
                    encoding="utf-8",
                )
                fh.setFormatter(logging.Formatter("%(message)s"))
                self._logger.addHandler(fh)
            except Exception as e:  # non-fatal: audit must never break a query
                print(f"[AUDIT] WARNING: audit log not writable ({path}): {e}",
                      file=sys.stderr)

    def write(self, event: dict):
        try:
            event = {"ts": datetime.now(UTC).isoformat(), **event}
            self._logger.info(json.dumps(event, default=str))
        except Exception as e:
            print(f"[AUDIT] write failed: {e} | event={event.get('event')}",
                  file=sys.stderr)


# --------------------------------------------------------------------------- #
#  RateLimiter -- sliding window (mirrors app.py._check_rate_limit)
# --------------------------------------------------------------------------- #
class RateLimiter:
    """Sliding-window rate limiter. Thread-safe, per-user isolation.

    Matches app.py exactly: an event is kept while ``now - t < window`` (strict
    ``<``); if the in-window count reaches ``limit`` the request is blocked and
    nothing is recorded (the blocked path does NOT append).
    """

    def __init__(self, limit=None, window_sec=None):
        self.limit = limit if limit is not None else config.RATE_LIMIT_QUERIES
        self.window = window_sec if window_sec is not None else config.RATE_LIMIT_WINDOW_SEC
        self._lock = threading.Lock()
        self._times: dict[str, list[float]] = {}

    def check(self, user_id: str, now=time.time) -> bool:
        """Return True if allowed (and record it), False if blocked."""
        t = now()
        with self._lock:
            times = [x for x in self._times.get(user_id, []) if t - x < self.window]
            if len(times) >= self.limit:
                return False
            times.append(t)
            self._times[user_id] = times
            return True


# --------------------------------------------------------------------------- #
#  Module-level singletons mirroring app.py's process globals
# --------------------------------------------------------------------------- #
audit_log = Audit()
rate_limiter = RateLimiter()


def audit(event: dict):
    """Append an event to the default rotating audit trail."""
    audit_log.write(event)


def check_rate_limit(user_id: str) -> bool:
    """Sliding-window rate check against the default limiter."""
    return rate_limiter.check(user_id)
