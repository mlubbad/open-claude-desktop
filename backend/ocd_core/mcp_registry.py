"""Centralized MCP process registry (single-spawn) for VersoWork.

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
import os
import tempfile
import threading

from . import egress

_DEFAULT_TIMEOUT = float(__import__("os").getenv("MCP_CALL_TIMEOUT_SEC", "60"))


def _transport_of(cfg: dict) -> str:
    """Which transport this server uses: 'stdio' (a local command), 'sse' (legacy
    remote SSE), or 'http' (remote Streamable HTTP — the default for a url)."""
    if cfg.get("url"):
        t = (cfg.get("transport") or "http").strip().lower()
        return "sse" if t in ("sse", "sse-legacy") else "http"
    return "stdio"


def _server_key(cfg: dict) -> tuple:
    """Identity of a server: its id plus the connection details it opens."""
    ident = cfg.get("id") or cfg.get("url") or cfg.get("command")
    if cfg.get("url"):
        return (ident, cfg.get("url"), _transport_of(cfg))
    return (ident, cfg.get("command"), tuple(cfg.get("args", [])))


def _stdio_env(env: dict | None) -> dict | None:
    """Merge explicit env vars onto the MCP SDK's safe default environment (so a
    server sees PATH etc. plus its configured keys); None -> inherit the default."""
    if not env:
        return None
    base: dict = {}
    with contextlib.suppress(Exception):
        from mcp.client.stdio import get_default_environment
        base = dict(get_default_environment())
    base.update({k: str(v) for k, v in env.items()})
    return base


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


def _drain_errfile(errfile, keep: int = 300) -> str:
    """Read (and dispose) the stderr spool of a spawned stdio server, returning the
    last ``keep`` characters collapsed to one line. The child writes through a dup'd
    fd, so read from the path rather than the (offset-shared) handle."""
    if errfile is None:
        return ""
    tail = ""
    with contextlib.suppress(Exception):
        errfile.flush()
        with open(errfile.name, encoding="utf-8", errors="replace") as r:
            tail = " ".join(r.read().split())[-keep:]
    with contextlib.suppress(Exception):
        errfile.close()
    with contextlib.suppress(Exception):
        os.unlink(errfile.name)
    return tail


class _Session:
    """A live MCP ClientSession plus the AsyncExitStack holding its subprocess and,
    for stdio servers, the tempfile spooling the child's stderr (diagnostics)."""

    __slots__ = ("session", "stack", "errfile")

    def __init__(self, session, stack, errfile=None):
        self.session = session
        self.stack = stack
        self.errfile = errfile


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
        from mcp import ClientSession

        transport = _transport_of(cfg)
        stack = contextlib.AsyncExitStack()
        errfile = None
        try:
            if transport == "http":
                egress.assert_public_url(cfg["url"])
                # streamablehttp_client accepts headers= directly (the newer
                # streamable_http_client takes a pre-built httpx client instead).
                # An OAuth 2.1 provider (httpx.Auth) rides in via cfg["auth_provider"];
                # the registry stays protocol-agnostic — integrations builds it.
                from mcp.client.streamable_http import streamablehttp_client
                read, write, _ = await stack.enter_async_context(
                    streamablehttp_client(cfg["url"], headers=cfg.get("headers") or None,
                                          auth=cfg.get("auth_provider"),
                                          httpx_client_factory=(
                                              egress.mcp_httpx_client_factory
                                          )))
            elif transport == "sse":
                egress.assert_public_url(cfg["url"])
                # Same OAuth 2.1 provider ride-along as the http branch — previously
                # only Streamable-HTTP connectors could authenticate.
                from mcp.client.sse import sse_client
                read, write = await stack.enter_async_context(
                    sse_client(cfg["url"], headers=cfg.get("headers") or None,
                               auth=cfg.get("auth_provider"),
                               httpx_client_factory=egress.mcp_httpx_client_factory))
            else:
                from mcp import StdioServerParameters
                from mcp.client.stdio import stdio_client
                params = StdioServerParameters(
                    command=cfg["command"], args=list(cfg.get("args", [])),
                    env=_stdio_env(cfg.get("env")))
                # Spool the child's stderr so a failed spawn/handshake can show the
                # server's OWN words ("npm ERR! …", "docker: cannot connect …")
                # instead of a generic client-side error.
                errfile = tempfile.NamedTemporaryFile(
                    mode="w+", suffix=".mcp-stderr", delete=False,
                    encoding="utf-8", errors="replace")
                read, write = await stack.enter_async_context(
                    stdio_client(params, errlog=errfile))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            return _Session(session, stack, errfile)
        except Exception as e:
            with contextlib.suppress(BaseException):
                await stack.aclose()
            tail = _drain_errfile(errfile)
            if tail:
                base = str(e).strip() or type(e).__name__
                raise RuntimeError(f"{base} — server output: {tail}") from e
            raise
        except BaseException:
            with contextlib.suppress(BaseException):
                await stack.aclose()
            _drain_errfile(errfile)
            raise

    async def _close(self, key: tuple):
        sess = self._sessions.pop(key, None)
        if sess is not None:
            with contextlib.suppress(Exception):
                await sess.stack.aclose()
            _drain_errfile(sess.errfile)

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

    async def _list_resources(self, cfg: dict, timeout: float) -> list[dict]:
        sess = await self._get_session(cfg)
        try:
            resp = await asyncio.wait_for(sess.session.list_resources(), timeout=timeout)
        except BaseException:
            await self._close(_server_key(cfg))
            raise
        return [{"uri": str(r.uri), "name": r.name or "",
                 "description": r.description or "",
                 "mimeType": getattr(r, "mimeType", "") or ""}
                for r in resp.resources]

    async def _read_resource(self, cfg: dict, uri: str, timeout: float) -> str:
        from pydantic import AnyUrl
        sess = await self._get_session(cfg)
        try:
            resp = await asyncio.wait_for(
                sess.session.read_resource(AnyUrl(uri)), timeout=timeout)
        except BaseException:
            await self._close(_server_key(cfg))
            raise
        parts: list[str] = []
        for c in resp.contents:
            text = getattr(c, "text", None)
            if text is not None:
                parts.append(text)
            elif getattr(c, "blob", None) is not None:
                mime = getattr(c, "mimeType", "") or "application/octet-stream"
                parts.append(f"(binary content · {mime})")
        return "\n".join(parts) or "(empty)"

    async def _list_prompts(self, cfg: dict, timeout: float) -> list[dict]:
        sess = await self._get_session(cfg)
        try:
            resp = await asyncio.wait_for(sess.session.list_prompts(), timeout=timeout)
        except BaseException:
            await self._close(_server_key(cfg))
            raise
        return [{"name": p.name, "description": p.description or "",
                 "arguments": [{"name": a.name, "description": a.description or "",
                                "required": bool(getattr(a, "required", False))}
                               for a in (p.arguments or [])]}
                for p in resp.prompts]

    async def _get_prompt(self, cfg: dict, name: str, args: dict, timeout: float) -> dict:
        sess = await self._get_session(cfg)
        try:
            resp = await asyncio.wait_for(
                sess.session.get_prompt(name, args or {}), timeout=timeout)
        except BaseException:
            await self._close(_server_key(cfg))
            raise
        msgs = []
        for m in resp.messages:
            content = m.content
            text = getattr(content, "text", None)
            if text is None:
                text = str(getattr(content, "data", content))
            msgs.append({"role": str(m.role), "content": text})
        return {"description": resp.description or "", "messages": msgs}

    # ---- public, synchronous API --------------------------------------- #
    def call(self, cfg: dict, tool: str, args: dict,
             timeout: float = _DEFAULT_TIMEOUT) -> str:
        return self._submit(self._call(cfg, tool, args, timeout), timeout)

    def discover(self, cfg: dict, timeout: float = _DEFAULT_TIMEOUT) -> list[dict]:
        return self._submit(self._discover(cfg, timeout), timeout)

    def list_resources(self, cfg: dict, timeout: float = _DEFAULT_TIMEOUT) -> list[dict]:
        return self._submit(self._list_resources(cfg, timeout), timeout)

    def read_resource(self, cfg: dict, uri: str, timeout: float = _DEFAULT_TIMEOUT) -> str:
        return self._submit(self._read_resource(cfg, uri, timeout), timeout)

    def list_prompts(self, cfg: dict, timeout: float = _DEFAULT_TIMEOUT) -> list[dict]:
        return self._submit(self._list_prompts(cfg, timeout), timeout)

    def get_prompt(self, cfg: dict, name: str, args: dict,
                   timeout: float = _DEFAULT_TIMEOUT) -> dict:
        return self._submit(self._get_prompt(cfg, name, args, timeout), timeout)

    def drop(self, cfg: dict):
        """Forget a server (e.g. on remove/refresh) so its process is killed."""
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        with contextlib.suppress(Exception):
            asyncio.run_coroutine_threadsafe(
                self._close(_server_key(cfg)), loop).result(timeout=15)

    def drop_all(self):
        """Close every live session (but keep the loop running) so each server
        reconnects — and reloads its credentials — on next use. Used after an in-app
        re-auth: a connector that cached an expired token at startup would otherwise
        keep serving it until the process restarts."""
        loop = self._loop
        if loop is None or not loop.is_running():
            return

        async def _close_all():
            for key in list(self._sessions):
                await self._close(key)

        with contextlib.suppress(Exception):
            asyncio.run_coroutine_threadsafe(_close_all(), loop).result(timeout=15)

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
