"""Interactive tool-permission gate (HITL).

Suspends a running agent turn until the user approves or declines a sensitive tool
call, then resumes it. This lands *before* remote MCP transports and Cowork
working-folder access widen the attack surface (security-before-surface ordering) —
a prompt-injected, tool-enabled model must not silently run shell/code/DB/external
calls.

Modes (``PERMISSION_MODE``):
  * ``auto``   — no prompts (default; preserves prior behavior).
  * ``ask``    — prompt only for sensitive tools (code/shell/fs-write/DB/external).
  * ``strict`` — prompt for every tool.

The registry is in-process: correct for the local-first single-process target. A
self-hosted multi-worker server would need a shared channel (e.g. Redis pub/sub);
that is a documented later concern.
"""
from __future__ import annotations

import asyncio

# Read-only information tools never need approval, even in ``ask`` mode.
SAFE_TOOLS = frozenset({
    "search_schema", "search_project_knowledge", "search_past_chats", "web_search",
    "deep_research", "web_fetch", "memory",
})
# Builtins that run code, touch the filesystem, or hit a database → always sensitive.
# `authenticate` runs a host login CLI (opens a browser for OAuth consent).
SENSITIVE_TOOLS = frozenset({
    "bash", "code_execution", "text_editor", "run_sql", "authenticate",
})


def is_sensitive(name: str) -> bool:
    """A tool is sensitive if it runs code/commands, writes files, hits a DB, or calls
    an external service (MCP servers, REST connectors, and unknown plugin tools)."""
    if name in SENSITIVE_TOOLS:
        return True
    if name in SAFE_TOOLS:
        return False
    # External / user-supplied tools default to sensitive (fail-safe).
    return True


def _is_memory_mutation(name: str, args: dict | None) -> bool:
    """The memory tool is read-only 'safe' for `view`, but its create/str_replace/insert/
    delete/rename commands mutate the persistent per-project store — gate those so
    injected content can't silently poison or wipe memory without approval."""
    if name != "memory":
        return False
    cmd = ""
    if isinstance(args, dict):
        cmd = str(args.get("command", "")).strip().lower()
    return cmd not in ("", "view")


def requires_approval(name: str, mode: str | None, args: dict | None = None) -> bool:
    m = (mode or "auto").strip().lower()
    if m == "ask":
        return is_sensitive(name) or _is_memory_mutation(name, args)
    if m == "auto":
        return False
    # "strict" — and any UNRECOGNIZED mode — fails closed: prompt for every tool. A
    # typo'd or injected permission_mode must never silently disable the HITL gate.
    return True


class PermissionRegistry:
    """Maps (turn_id, tool_call_id) → a Future the reply endpoint resolves."""

    def __init__(self) -> None:
        self._pending: dict[tuple[str, str], asyncio.Future] = {}

    async def wait(self, turn_id: str, tc_id: str, timeout: float) -> bool:
        """Await the user's decision. Times out fail-closed (declined)."""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[(turn_id, tc_id)] = fut
        try:
            return bool(await asyncio.wait_for(fut, timeout))
        except TimeoutError:
            return False
        finally:
            self._pending.pop((turn_id, tc_id), None)

    def resolve(self, turn_id: str, tc_id: str, approved: bool) -> bool:
        """Deliver a decision into a suspended turn. Returns True if one was waiting."""
        fut = self._pending.get((turn_id, tc_id))
        if fut is not None and not fut.done():
            fut.set_result(bool(approved))
            return True
        return False

    def pending(self, turn_id: str) -> list[str]:
        return [tc for (t, tc) in self._pending if t == turn_id]


registry = PermissionRegistry()
