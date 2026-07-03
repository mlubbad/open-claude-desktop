"""MCP transport routing (stdio/http/sse), per-server env, and a real Streamable-HTTP
end-to-end against an in-process FastMCP server."""
import socket
import threading
import time

import pytest
from ocd_core import mcp_registry
from ocd_core.mcp_registry import _server_key, _stdio_env, _transport_of


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


def test_streamable_http_end_to_end():
    """Start a FastMCP server over Streamable HTTP and drive it through the registry."""
    import uvicorn
    from mcp.server.fastmcp import FastMCP

    port = _free_port()
    mcp = FastMCP("test-remote", host="127.0.0.1", port=port)

    @mcp.tool()
    def echo(text: str) -> str:
        return text

    app = mcp.streamable_http_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                            lifespan="on")
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # off the main thread

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    cfg = {"id": "remote-test", "url": f"http://127.0.0.1:{port}/mcp", "transport": "http"}
    try:
        # Wait for the server to accept a real MCP session.
        tools = None
        for _ in range(50):
            try:
                tools = mcp_registry.registry.discover(cfg, timeout=5)
                break
            except Exception:
                time.sleep(0.2)
        assert tools is not None, "remote MCP server never became ready"
        assert any(t["name"] == "echo" for t in tools)

        result = mcp_registry.registry.call(cfg, "echo", {"text": "hello remote"}, timeout=5)
        assert "hello remote" in result
    finally:
        mcp_registry.registry.drop(cfg)
        server.should_exit = True


@pytest.fixture(autouse=True)
def _reset_registry():
    yield
