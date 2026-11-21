"""Temporary fail-fast request limits for containment.

The Compose proxy owns the first enforcement layer. This pure ASGI middleware is a
second backstop for direct desktop/development launches and for chunked bodies whose
declared Content-Length is absent or false. Concurrency is intentionally process-local;
a distributed gateway must replace it before horizontal production scaling.
"""
from __future__ import annotations

import asyncio

from starlette.responses import JSONResponse


class RequestBodyTooLarge(Exception):
    """Raised internally when streamed request bytes cross the configured cap."""


class ConcurrencyGate:
    """Atomic, non-queueing process-local concurrency gate."""

    def __init__(self, limit: int):
        self.limit = max(1, int(limit))
        self._active = 0
        self._lock = asyncio.Lock()

    async def try_acquire(self) -> bool:
        async with self._lock:
            if self._active >= self.limit:
                return False
            self._active += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            if self._active > 0:
                self._active -= 1


class RequestLimitsMiddleware:
    """Reject oversized or excess concurrent HTTP requests without queue buildup."""

    _CONCURRENCY_EXEMPT = frozenset({"/healthz", "/readyz"})

    def __init__(self, app, *, max_request_bytes: int, max_concurrent: int):
        self.app = app
        self.max_request_bytes = max(1, int(max_request_bytes))
        self.gate = ConcurrencyGate(max_concurrent)

    @staticmethod
    def _content_length(scope) -> int | None:
        values = [value for name, value in scope.get("headers", [])
                  if name.lower() == b"content-length"]
        if not values:
            return None
        if len(values) != 1:
            raise ValueError("multiple Content-Length headers")
        value = values[0].decode("ascii", errors="strict").strip()
        length = int(value)
        if length < 0:
            raise ValueError("negative Content-Length")
        return length

    @staticmethod
    async def _reject(scope, receive, send, status: int, detail: str, *, retry=False):
        headers = {"Retry-After": "1"} if retry else None
        response = JSONResponse({"detail": detail}, status_code=status, headers=headers)
        await response(scope, receive, send)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        try:
            content_length = self._content_length(scope)
        except (UnicodeDecodeError, ValueError):
            await self._reject(scope, receive, send, 400, "invalid Content-Length")
            return
        if content_length is not None and content_length > self.max_request_bytes:
            await self._reject(scope, receive, send, 413, "request body too large")
            return

        gated = scope.get("path", "") not in self._CONCURRENCY_EXEMPT
        if gated and not await self.gate.try_acquire():
            await self._reject(
                scope, receive, send, 503, "request concurrency limit reached", retry=True
            )
            return

        received = 0
        response_started = False

        async def limited_receive():
            nonlocal received
            message = await receive()
            if message.get("type") == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_request_bytes:
                    raise RequestBodyTooLarge
            return message

        async def tracked_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracked_send)
        except RequestBodyTooLarge:
            if response_started:
                raise
            await self._reject(scope, receive, send, 413, "request body too large")
        finally:
            if gated:
                await self.gate.release()
