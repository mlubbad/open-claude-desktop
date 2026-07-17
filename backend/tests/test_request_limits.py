import asyncio
import importlib
from pathlib import Path


def test_request_limit_defaults_are_bounded(monkeypatch):
    monkeypatch.delenv("OCD_MAX_REQUEST_BYTES", raising=False)
    monkeypatch.delenv("OCD_MAX_CONCURRENT_REQUESTS", raising=False)
    from ocd_core import config

    cfg = importlib.reload(config)
    assert cfg.MAX_REQUEST_BYTES == 32 * 1024 * 1024
    assert cfg.MAX_CONCURRENT_REQUESTS == 32


def test_content_length_over_limit_is_rejected_before_dispatch():
    from app.request_limits import RequestLimitsMiddleware

    called = False

    async def inner(scope, receive, send):
        nonlocal called
        called = True

    middleware = RequestLimitsMiddleware(inner, max_request_bytes=4, max_concurrent=2)
    messages = []
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/upload",
        "headers": [(b"content-length", b"5")],
    }

    async def receive():
        return {"type": "http.request", "body": b"12345", "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.run(middleware(scope, receive, send))
    assert called is False
    assert messages[0]["status"] == 413


def test_streamed_body_over_limit_is_rejected():
    from app.request_limits import RequestLimitsMiddleware

    async def consuming_app(scope, receive, send):
        while True:
            message = await receive()
            if not message.get("more_body"):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    incoming = iter([
        {"type": "http.request", "body": b"abc", "more_body": True},
        {"type": "http.request", "body": b"de", "more_body": False},
    ])
    sent = []

    async def receive():
        return next(incoming)

    async def send(message):
        sent.append(message)

    middleware = RequestLimitsMiddleware(
        consuming_app, max_request_bytes=4, max_concurrent=2
    )
    scope = {"type": "http", "method": "POST", "path": "/upload", "headers": []}
    asyncio.run(middleware(scope, receive, send))
    assert sent[0]["status"] == 413


def test_concurrency_gate_rejects_without_queueing():
    from app.request_limits import ConcurrencyGate

    async def exercise():
        gate = ConcurrencyGate(1)
        assert await gate.try_acquire() is True
        assert await gate.try_acquire() is False
        await gate.release()
        assert await gate.try_acquire() is True
        await gate.release()

    asyncio.run(exercise())


def test_temporary_proxy_policy_is_wired_into_compose():
    root = Path(__file__).resolve().parents[2]
    policy = (root / "deploy" / "nginx" / "containment.conf").read_text()
    compose = (root / "docker-compose.yml").read_text()

    assert "client_max_body_size 32m" in policy
    assert "limit_conn_zone" in policy and "limit_conn ocd_conn 32" in policy
    assert "limit_req_zone" in policy and "limit_req zone=ocd_rate" in policy
    assert "server backend:8000" in policy
    assert "proxy:" in compose
    assert "./deploy/nginx/containment.conf" in compose
