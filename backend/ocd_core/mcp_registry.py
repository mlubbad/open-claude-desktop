"""Centralized MCP process registry (single-spawn) for Open Claude Desktop.

Previously every MCP tool call spawned a fresh stdio subprocess (asyncio.run +
stdio_client) and tore it down — N calls => N fork/execs, no pooling, no
timeout, and a slow/hung server could block indefinitely. This module keeps
ONE long-lived MCP ClientSession per server, reused across all UI panels and
agent turns, with per-call timeouts and clean shutdown.

Why a dedicated thread+loop: an MCP ClientSession (and its stdio transport) is
bound to the asyncio event loop that created it, but the app calls MCP from
sync contexts (Reflex/Chainlit worker threads). So the registry owns a single
daemon thread running one event loop; all session creation and calls are
marshaled onto it via run_coroutine_threadsafe. The session's background
reader task lives on that loop for the process lifetime.
"""
from __future__ import annotations

import asyncio
import atexit
import contextlib
import json
import threading

_DEFAULT_TIMEOUT = float(__import__("os").getenv("MCP_CALL_TIMEOUT_SEC", "60"))


def _server_key(cfg: dict) -> tuple:
    """Identity of a server: its id plus the exact command+args it launches."""
    return (cfg.get("id") or cfg.get("command"),
            cfg.get("command"), tuple(cfg.get("args", [])))


def _render(res) -> str:
    """Flatten an MCP call_tool result into a single string (text + structured)."""
    parts: list[str] = []
    for c in getattr(res, "content", []) or []:
        if getattr(c, "type", "") == "text":
            parts.append(c.text)
        else:
            parts.append(str(getattr(c, "data", c)))
    out = "\n".join(p for p in parts if p)
    if getattr(res, "structuredContent", None):
        out = (out + "\n" + json.dumps(res.structuredContent, default=str)).strip()
    return out or "(no content)"


class _Session:
    """A live MCP ClientSession plus the AsyncExitStack holding its subprocess."""

    __slots__ = ("session", "stack")

    def __init__(self, session, stack):
        self.session = session
        self.stack = stack


class MCPRegistry:
    """Single-spawn registry: one persistent ClientSession per server key."""

    def __init__(self):
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._boot_lock = threading.Lock()       # guards loop/thread creation
        self._sessions: dict[tuple, _Session] = {}   # mutated only on the loop
        self._key_locks: dict[tuple, asyncio.Lock] = {}  # created on the loop

    # ---- dedicated loop lifecycle -------------------------------------- #
    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        with self._boot_lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop
            loop = asyncio.new_event_loop()  # Proactor on Windows => subprocess OK
            thread = threading.Thread(target=self._run_loop, args=(loop,),
                                      name="mcp-registry", daemon=True)
            thread.start()
            self._loop, self._thread = loop, thread
            return loop

    @staticmethod
    def _run_loop(loop: asyncio.AbstractEventLoop):
        asyncio.set_event_loop(loop)
        loop.run_forever()

    def _submit(self, coro, timeout: float):
        """Run a coroutine on the registry loop from a sync caller and block."""
        loop = self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        # Outer guard is slightly longer than the inner wait_for so the inner
        # timeout (which also tears the session down) wins on a slow server.
        return fut.result(timeout=timeout + 10)

    # ---- session management (all of this runs ON the registry loop) ----- #
    def _key_lock(self, key: tuple) -> asyncio.Lock:
        lock = self._key_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._key_locks[key] = lock
        return lock

    async def _open_session(self, cfg: dict) -> _Session:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        stack = contextlib.AsyncExitStack()
        try:
            params = StdioServerParameters(
                command=cfg["command"], args=list(cfg.get("args", [])), env=None)
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            return _Session(session, stack)
        except BaseException:
            await stack.aclose()
            raise

    async def _close(self, key: tuple):
        sess = self._sessions.pop(key, None)
        if sess is not None:
            with contextlib.suppress(Exception):
                await sess.stack.aclose()

    async def _get_session(self, cfg: dict) -> _Session:
        key = _server_key(cfg)
        async with self._key_lock(key):
            sess = self._sessions.get(key)
            if sess is not None:
                return sess
            sess = await self._open_session(cfg)
            self._sessions[key] = sess
            return sess

    async def _call(self, cfg: dict, tool: str, args: dict, timeout: float) -> str:
        sess = await self._get_session(cfg)
        try:
            res = await asyncio.wait_for(
                sess.session.call_tool(tool, args or {}), timeout=timeout)
        except BaseException:
            # Drop the (possibly broken) session so the next call respawns it.
            await self._close(_server_key(cfg))
            raise
        return _render(res)

    async def _discover(self, cfg: dict, timeout: float) -> list[dict]:
        sess = await self._get_session(cfg)
        try:
            resp = await asyncio.wait_for(sess.session.list_tools(), timeout=timeout)
        except BaseException:
            await self._close(_server_key(cfg))
            raise
        return [{"name": t.name, "description": t.description or "",
                 "inputSchema": (t.inputSchema
                                 or {"type": "object", "properties": {}})}
                for t in resp.tools]

    # ---- public, synchronous API --------------------------------------- #
    def call(self, cfg: dict, tool: str, args: dict,
             timeout: float = _DEFAULT_TIMEOUT) -> str:
        return self._submit(self._call(cfg, tool, args, timeout), timeout)

    def discover(self, cfg: dict, timeout: float = _DEFAULT_TIMEOUT) -> list[dict]:
        return self._submit(self._discover(cfg, timeout), timeout)

    def drop(self, cfg: dict):
        """Forget a server (e.g. on remove/refresh) so its process is killed."""
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        with contextlib.suppress(Exception):
            asyncio.run_coroutine_threadsafe(
                self._close(_server_key(cfg)), loop).result(timeout=15)

    def shutdown(self):
        loop = self._loop
        if loop is None or not loop.is_running():
            return

        async def _close_all():
            for key in list(self._sessions):
                await self._close(key)

        with contextlib.suppress(Exception):
            asyncio.run_coroutine_threadsafe(_close_all(), loop).result(timeout=15)
        loop.call_soon_threadsafe(loop.stop)


# Module-level singleton shared by all callers + best-effort cleanup at exit.
registry = MCPRegistry()
atexit.register(registry.shutdown)
