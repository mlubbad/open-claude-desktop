"""
A tiny, self-contained MCP (Model Context Protocol) server bundled with AJ360.

It exists so the app's MCP *client* connector has a real server to talk to out of
the box — no network, no secrets, no external downloads. Register it from the
composer's Connectors → MCP submenu (the app pre-fills this file's path), and its
tools become available to the agent as `mcp_<server>_<tool>`.

Run standalone for a sanity check:
    python mcp_servers/demo_server.py     # speaks MCP over stdio
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("aj360-demo")


@mcp.tool()
def echo(text: str) -> str:
    """Echo the given text back unchanged."""
    return text


@mcp.tool()
def server_time() -> str:
    """Return the current local server time as an ISO-8601 string."""
    from datetime import datetime
    return datetime.now().isoformat(timespec="seconds")


@mcp.tool()
def word_count(text: str) -> int:
    """Count the whitespace-separated words in the given text."""
    return len((text or "").split())


@mcp.tool()
def reverse(text: str) -> str:
    """Reverse the characters of the given text."""
    return (text or "")[::-1]


if __name__ == "__main__":
    mcp.run()
