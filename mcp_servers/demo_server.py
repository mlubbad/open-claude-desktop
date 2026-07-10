"""
A tiny, self-contained MCP (Model Context Protocol) server bundled with Open Claude Desktop.

It exists so the app's MCP *client* connector always has a real server to talk to
— no network, no secrets, no external downloads. Add it as a local (stdio) connector
pointing `command` at this file, and its tools become available to the agent as
`mcp_<server>_<tool>`. It also backs the MCP registry's integration test.

Run standalone for a sanity check:
    python mcp_servers/demo_server.py     # speaks MCP over stdio
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ocd-demo")


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
