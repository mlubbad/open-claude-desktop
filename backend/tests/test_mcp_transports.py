"""MCP transport routing (stdio/http/sse), per-server env, and a real Streamable-HTTP
end-to-end against an in-process FastMCP server."""
import contextlib
import socket
import threading
import time

import pytest
from ocd_core import mcp_registry
from ocd_core.mcp_registry import _server_key, _stdio_env, _transport_of


@pytest.fixture(autouse=True)
def _allow_test_loopback(monkeypatch):
    """The in-process fixture is loopback; production MCP egress blocks it.

    Egress now refuses loopback at two layers: assert_public_url's pre-flight
    check and the connect-time pin (_resolve_ips, which the pinned transport
    calls just before opening the socket). Neutralize both so the test can reach
    its own in-process server -- exactly the address production is right to
    refuse. _resolve_ips still does a real resolution here; only the
    private/non-routable rejection is lifted."""
    from ocd_core import egress

    monkeypatch.setattr(egress, "assert_public_url", lambda url, **_kwargs: url)
    monkeypatch.setattr(
        egress,
        "_resolve_ips",
        lambda host, port: [str(a) for a in egress._resolved_addresses(host, port)],
    )


def test_transport_of():
    assert _transport_of({"command": "python"}) == "stdio"
    assert _transport_of({"url": "http://x/mcp"}) == "http"
    assert _transport_of({"url": "http://x/mcp", "transport": "sse"}) == "sse"
    assert _transport_of({"url": "http://x/mcp", "transport": "HTTP"}) == "http"


def test_server_key_distinguishes_stdio_and_remote():
    stdio = _server_key({"id": "a", "command": "python", "args": ["x.py"]})
    remote = _server_key({"id": "a", "url": "http://h/mcp", "transport": "http"})
    assert stdio != remote
    assert remote[1] == "http://h/mcp"


def test_stdio_env_merges_and_passes_through_none():
    assert _stdio_env(None) is None
    merged = _stdio_env({"API_KEY": "secret"})
    assert merged is not None and merged.get("API_KEY") == "secret"


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _build_server():
    """A FastMCP server exposing a tool, a resource, and a prompt."""
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("test-remote")

    @mcp.tool()
    def echo(text: str) -> str:
        return text

    @mcp.resource("greeting://hello")
    def greeting() -> str:
        return "hello resource"

    @mcp.prompt()
    def summarize(text: str) -> str:
        return f"Please summarize: {text}"

    return mcp


@contextlib.contextmanager
def _serve():
    """Serve _build_server() over Streamable HTTP and yield a ready registry cfg."""
    import uvicorn

    port = _free_port()
    app = _build_server().streamable_http_app()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
                                           log_level="warning", lifespan="on"))
    server.install_signal_handlers = lambda: None  # off the main thread
    threading.Thread(target=server.run, daemon=True).start()

    cfg = {"id": "remote-test", "url": f"http://127.0.0.1:{port}/mcp", "transport": "http"}
    try:
        for _ in range(50):
            try:
                mcp_registry.registry.discover(cfg, timeout=5)
                break
            except Exception:
                time.sleep(0.2)
        else:
            raise AssertionError("remote MCP server never became ready")
        yield cfg
    finally:
        mcp_registry.registry.drop(cfg)
        server.should_exit = True


def test_streamable_http_tools_end_to_end():
    with _serve() as cfg:
        tools = mcp_registry.registry.discover(cfg, timeout=5)
        assert any(t["name"] == "echo" for t in tools)
        result = mcp_registry.registry.call(cfg, "echo", {"text": "hello remote"}, timeout=5)
        assert "hello remote" in result


def test_streamable_http_resources_and_prompts():
    with _serve() as cfg:
        resources = mcp_registry.registry.list_resources(cfg, timeout=5)
        assert any(r["uri"].startswith("greeting://") for r in resources)
        content = mcp_registry.registry.read_resource(cfg, "greeting://hello", timeout=5)
        assert "hello resource" in content

        prompts = mcp_registry.registry.list_prompts(cfg, timeout=5)
        assert any(p["name"] == "summarize" for p in prompts)
        got = mcp_registry.registry.get_prompt(cfg, "summarize", {"text": "the doc"}, timeout=5)
        rendered = " ".join(m["content"] for m in got["messages"])
        assert "Please summarize: the doc" in rendered
