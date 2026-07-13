"""A redacted operational snapshot for support / bug reports ("Export diagnostics").

Contains NO secrets — API keys live in the OS keychain, never in settings — and the
personal profile is reduced to a presence flag so a shared bundle can't leak personal
notes. Everything here is derived, read-only, and best-effort: a failing probe degrades
to a marker rather than raising, so diagnostics always returns something useful.
"""
from __future__ import annotations

import contextlib
import platform
import sys

from . import config
from .db import engine


def _counts() -> dict:
    """Rough inventory of local data (best-effort; any failure → -1 for that count)."""
    out = {"projects": -1, "conversations": -1, "schedules": -1, "cowork_tasks": -1}
    with contextlib.suppress(Exception):
        from . import projects
        out["projects"] = len(projects.list_projects(include_archived=True))
    with contextlib.suppress(Exception):
        from . import conversations
        out["conversations"] = len(conversations.list_all_conversations(limit=100000))
    with contextlib.suppress(Exception):
        from . import scheduler
        out["schedules"] = len(scheduler.service.list())
    with contextlib.suppress(Exception):
        from . import cowork
        out["cowork_tasks"] = len(cowork.manager.list())
    return out


def collect() -> dict:
    """Assemble the diagnostics snapshot (see module docstring for the redaction rules)."""
    from . import settings
    s = dict(settings.get_settings())
    # The profile may hold personal notes; a diagnostics bundle can be shared with
    # support, so report only whether one is set — never its contents.
    s["profile"] = {"present": bool(s.get("profile"))}

    url = engine.database_url()
    reachable = False
    with contextlib.suppress(Exception):
        engine.get_engine().connect().close()
        reachable = True

    return {
        "app": {"name": config.APP_NAME, "backend_version": config.BACKEND_VERSION},
        "platform": {
            "system": platform.platform(),
            "python": sys.version.split()[0],
            "frozen": bool(getattr(sys, "frozen", False)),  # packaged (PyInstaller) vs dev
        },
        "data_root": str(config.REPO_ROOT),
        # Only the scheme — a full DATABASE_URL can carry a host/user (and, misconfigured,
        # a password). Scheme + reachability is what a support triage actually needs.
        "database": {"scheme": url.split(":", 1)[0], "reachable": reachable},
        "settings": s,
        "counts": _counts(),
    }
