"""ocd_core — the framework-agnostic core of Open Claude Desktop.

It owns every domain concern (agent loop + typed streaming events, LLM/MCP clients,
tools, projects/conversations/knowledge, auth, secrets, persistence) and imports no
UI or transport. The FastAPI backend, the `ocd` CLI, and the desktop app are all thin
frontends over this one engine.
"""
