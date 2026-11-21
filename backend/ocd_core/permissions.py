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

from . import tenancy

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
    """Maps workspace/turn/tool-call identities to pending decisions."""

    def __init__(self) -> None:
        self._pending: dict[tuple[str, str, str], asyncio.Future] = {}
        self._metadata: dict[tuple[str, str, str], tuple[str, dict]] = {}

    @staticmethod
    def _workspace() -> str:
        if tenancy.enforcing():
            return tenancy.current_workspace()
        return tenancy.LOCAL_WORKSPACE

    @staticmethod
    def _record_id(turn_id: str, tc_id: str) -> str:
        return f"{turn_id}:{tc_id}"

    def describe(
        self, turn_id: str, tc_id: str, *, tool_name: str, args: dict | None
    ) -> None:
        """Attach auditable context while keeping the historic wait API mockable."""
        self._metadata[(self._workspace(), turn_id, tc_id)] = (
            tool_name,
            dict(args or {}),
        )

    @staticmethod
    def _persist(
        workspace: str,
        turn_id: str,
        tc_id: str,
        status: str,
        *,
        tool_name: str = "",
        args: dict | None = None,
    ) -> None:
        if not tenancy.enforcing():
            return
        from . import workspace_store

        with tenancy.use_workspace(workspace):
            previous = workspace_store.get_approval(
                PermissionRegistry._record_id(turn_id, tc_id)
            ) or {}
            workspace_store.upsert_approval({
                **previous,
                "id": PermissionRegistry._record_id(turn_id, tc_id),
                "turn_id": turn_id,
                "tool_call_id": tc_id,
                "tool_name": tool_name or str(previous.get("tool_name") or ""),
                "args": dict(args or previous.get("args") or {}),
                "status": status,
            })

    async def wait(
        self,
        turn_id: str,
        tc_id: str,
        timeout: float,
        *,
        tool_name: str = "",
        args: dict | None = None,
    ) -> bool:
        """Await the user's decision. Times out fail-closed (declined)."""
        workspace = self._workspace()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        key = (workspace, turn_id, tc_id)
        prepared_name, prepared_args = self._metadata.pop(key, ("", {}))
        tool_name = tool_name or prepared_name
        args = args or prepared_args
        self._pending[key] = fut
        self._persist(
            workspace, turn_id, tc_id, "pending", tool_name=tool_name, args=args
        )
        try:
            return bool(await asyncio.wait_for(fut, timeout))
        except TimeoutError:
            self._persist(workspace, turn_id, tc_id, "expired")
            return False
        finally:
            self._pending.pop(key, None)
            self._metadata.pop(key, None)

    def resolve(self, turn_id: str, tc_id: str, approved: bool) -> bool:
        """Deliver a decision into a suspended turn. Returns True if one was waiting."""
        workspace = self._workspace()
        fut = self._pending.get((workspace, turn_id, tc_id))
        if fut is not None and not fut.done():
            self._persist(
                workspace, turn_id, tc_id, "approved" if approved else "declined"
            )
            fut.set_result(bool(approved))
            return True
        return False

    def pending(self, turn_id: str) -> list[str]:
        workspace = self._workspace()
        return [
            tc
            for (candidate_workspace, candidate_turn, tc) in self._pending
            if candidate_workspace == workspace and candidate_turn == turn_id
        ]


registry = PermissionRegistry()
