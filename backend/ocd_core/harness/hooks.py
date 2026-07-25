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

import asyncio
import json
import re
import shlex
import time
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
    exit 2         -> deny for a blocking event (stderr is the reason), else no opinion
    other non-zero -> deny for a blocking event, else no opinion
    """
    out = (stdout or "").strip()[:config.HOOK_OUTPUT_MAX_CHARS]
    err = (stderr or "").strip()[:config.HOOK_OUTPUT_MAX_CHARS]
    if code == 2:
        if event in BLOCKING_EVENTS:
            return HookDecision(decision="deny", reason=err or "hook exited 2 (blocked)")
        return HookDecision(reason=err or "hook exited 2")
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


def _timeout_for(hook: dict) -> int:
    try:
        t = int(hook.get("timeout") or config.HOOK_TIMEOUT_SEC)
    except (TypeError, ValueError):
        t = config.HOOK_TIMEOUT_SEC
    return max(1, min(t, config.HOOK_TIMEOUT_MAX_SEC))


async def _run_one(hook: dict, event: str, payload: dict, cwd: str | None) -> HookDecision:
    """Execute ONE hook. Never raises — every failure becomes a HookDecision."""
    from .. import integrations, observability
    cmd = str(hook.get("command") or "")
    timeout = _timeout_for(hook)
    started = time.monotonic()
    try:
        parts = shlex.split(cmd, posix=False)
    except ValueError:
        return _fail(event, f"hook command could not be parsed: {cmd!r}")
    if not parts:
        return _fail(event, "hook command was empty")
    # posix=False keeps Windows paths intact but leaves quotes on tokens — strip them.
    parts = [p.strip('"') for p in parts]
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            *parts, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, cwd=cwd,
            env=integrations._sanitized_child_env())
        raw = json.dumps({"event": event, **payload}).encode("utf-8")
        out_b, err_b = await asyncio.wait_for(proc.communicate(raw), timeout=timeout)
        decision = parse_output(proc.returncode, out_b.decode("utf-8", "replace"),
                                err_b.decode("utf-8", "replace"), event)
    except TimeoutError:            # asyncio.TimeoutError is an alias of the builtin
        if proc is not None:
            try:
                proc.kill()
                # Reap it: without this the transport is torn down by GC later, which
                # leaks a dangling pipe/loop reference (the process itself IS killed).
                await proc.wait()
            except (OSError, ProcessLookupError):
                pass
        decision = _fail(event, f"hook timed out after {timeout}s: {cmd}")
    except (OSError, ValueError) as e:                 # not found, bad exe, etc.
        decision = _fail(event, f"hook could not run ({e}): {cmd}")
    # Scrub anything secret-shaped a hook printed before it reaches the model or the log.
    decision.reason = integrations._scrub_secrets(decision.reason)
    decision.context = integrations._scrub_secrets(decision.context)
    observability.audit({"event": "hook_run", "hook_event": event,
                         "command": cmd, "tool": payload.get("tool_name"),
                         "decision": decision.decision or "none",
                         "duration_ms": int((time.monotonic() - started) * 1000),
                         "ok": not decision.denied})
    return decision


async def run(event: str, payload: dict, cwd: str | None = None) -> HookDecision:
    """Run every hook matching ``event`` (and the payload's tool_name) and merge the
    results. Returns a no-opinion decision when nothing is configured — costing no
    subprocess and leaving the turn byte-for-byte as it was before hooks existed."""
    configured = load_hooks(event)
    if not configured:
        return HookDecision()
    tool = payload.get("tool_name")
    applicable = [h for h in configured if matches(h, tool)]
    if not applicable:
        return HookDecision()
    results = [await _run_one(h, event, payload, cwd) for h in applicable]
    return merge(results)
