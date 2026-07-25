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

import json
import re
from dataclasses import dataclass

from .. import config, settings

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


def matches(hook: dict, tool_name: str | None) -> bool:
    """Does ``hook``'s matcher apply to ``tool_name``? A missing/empty/``*`` matcher
    matches everything; otherwise it is a FULLY-ANCHORED regex on the tool name (so
    "edit" does not match "edit_file"). Non-tool events pass tool_name=None and always
    match. A malformed regex matches nothing (fail closed toward not-running the hook)."""
    if tool_name is None:
        return True
    m = str(hook.get("matcher") or "").strip()
    if not m or m == "*":
        return True
    try:
        return re.fullmatch(m, tool_name) is not None
    except re.error:
        return False


_VALID_DECISIONS = ("allow", "deny", "ask")
#: Strictness order — a later entry beats an earlier one when hooks disagree.
_STRICTNESS = {None: 0, "allow": 1, "ask": 2, "deny": 3}


def _fail(event: str, reason: str) -> HookDecision:
    """A hook failure: deny for a blocking event (fail closed), no-opinion otherwise."""
    if event in BLOCKING_EVENTS:
        return HookDecision(decision="deny", reason=reason)
    return HookDecision(reason=reason)


def parse_output(code: int, stdout: str, stderr: str, event: str) -> HookDecision:
    """Turn one hook's exit code + streams into a decision.

    exit 0 + JSON  -> that decision/context;  exit 0 + non-JSON -> no opinion
    exit 2         -> deny (stderr is the reason)
    other non-zero -> deny for a blocking event, else no opinion
    """
    out = (stdout or "").strip()[:config.HOOK_OUTPUT_MAX_CHARS]
    err = (stderr or "").strip()[:config.HOOK_OUTPUT_MAX_CHARS]
    if code == 2:
        return HookDecision(decision="deny", reason=err or "hook exited 2 (blocked)")
    if code != 0:
        return _fail(event, f"hook failed (exit {code}): {err or 'no stderr'}")
    if not out.startswith("{"):
        return HookDecision()                      # plain log output — no opinion
    try:
        data = json.loads(out)
    except ValueError:
        return _fail(event, "hook emitted malformed JSON")
    if not isinstance(data, dict):
        return _fail(event, "hook JSON was not an object")
    dec = data.get("permissionDecision")
    if dec is not None and dec not in _VALID_DECISIONS:
        return _fail(event, f"hook returned an unknown decision: {dec!r}")
    return HookDecision(decision=dec, reason=str(data.get("reason") or ""),
                        context=str(data.get("additionalContext") or ""))


def merge(decisions: list) -> HookDecision:
    """Combine several hooks' outcomes: the STRICTEST decision wins; contexts concatenate."""
    best = HookDecision()
    ctx, reasons = [], []
    for d in decisions:
        if _STRICTNESS.get(d.decision, 0) > _STRICTNESS.get(best.decision, 0):
            best = HookDecision(decision=d.decision, reason=d.reason)
        if d.context:
            ctx.append(d.context)
        if d.reason:
            reasons.append(d.reason)
    return HookDecision(decision=best.decision,
                        reason=best.reason or "; ".join(reasons),
                        context="\n".join(ctx))
