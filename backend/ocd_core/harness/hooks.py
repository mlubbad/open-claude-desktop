"""Harness lifecycle hooks — deterministic, user-owned interception points.

A hook is a shell command run at a lifecycle event: it receives the event as JSON on
stdin and returns a decision on stdout (or via its exit code). Hooks run OUTSIDE the
model's context — they cost no tokens and the model cannot argue with them.

Security posture (see docs/superpowers/specs/2026-07-22-harness-hooks-design.md):
  * Hooks come from APP SETTINGS ONLY — never from a workspace's .claude/settings.json.
    A workspace may contribute permission RULES (which only restrict); a hook EXECUTES.
  * PreToolUse fails CLOSED (timeout/crash/garbage -> deny); observational events fail OPEN.
  * A hook can only TIGHTEN a decision, never loosen one (see agent.py's gate ordering).
"""
from __future__ import annotations

from dataclasses import dataclass

from .. import settings

EVENTS = ("SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop")
#: Events whose failure must BLOCK (fail closed). Everything else is observational.
BLOCKING_EVENTS = ("PreToolUse", "UserPromptSubmit")


@dataclass
class HookDecision:
    """Merged outcome of every hook that matched an event."""
    decision: str | None = None      # "allow" | "deny" | "ask" | None (no opinion)
    reason: str = ""
    context: str = ""                # additionalContext to inject

    @property
    def denied(self) -> bool:
        return self.decision == "deny"


def load_hooks(event: str) -> list[dict]:
    """Hook configs for ``event`` from app settings. Returns [] when unconfigured or
    malformed — a bad config must never crash a turn."""
    if event not in EVENTS:
        return []
    try:
        raw = (settings.get_settings() or {}).get("hooks") or {}
        entries = raw.get(event) or []
    except Exception:
        return []
    out = []
    for e in entries if isinstance(entries, list) else []:
        if isinstance(e, dict) and str(e.get("command") or "").strip():
            out.append(e)
    return out
