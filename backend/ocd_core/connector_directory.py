"""Curated directory of well-known, free/open-source MCP servers (P1-3).

The Claude Desktop analog is the connectors directory ("browse connectors"). Ours is
a static, offline catalog of the official reference servers plus a few widely-used
open ones — each entry prefills the existing add-connector form (the user reviews the
command/URL and confirms), so nothing installs or executes without an explicit add.

Entries deliberately carry NO secrets; servers that need one (e.g. GitHub) declare it
in ``env_keys`` and the form's env field is where the user provides it.
"""
from __future__ import annotations

DIRECTORY: list[dict] = [
    {"id": "filesystem", "name": "Filesystem",
     "description": "Read, write, and search files in folders you choose. "
                    "Replace the path argument with the folder to expose.",
     "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-filesystem", "~/Documents"],
     "env_keys": [], "runtime": "node", "tags": ["files", "official"]},
    {"id": "fetch", "name": "Fetch",
     "description": "Fetch web pages and convert them to markdown for reading.",
     "transport": "stdio", "command": "uvx", "args": ["mcp-server-fetch"],
     "env_keys": [], "runtime": "python", "tags": ["web", "official"]},
    {"id": "git", "name": "Git",
     "description": "Inspect and search local git repositories (log, diff, blame).",
     "transport": "stdio", "command": "uvx", "args": ["mcp-server-git"],
     "env_keys": [], "runtime": "python", "tags": ["dev", "official"]},
    {"id": "github", "name": "GitHub",
     "description": "Issues, PRs, and repositories via the GitHub API. Needs a "
                    "personal access token in the env field.",
     "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-github"],
     "env_keys": ["GITHUB_PERSONAL_ACCESS_TOKEN"], "runtime": "node",
     "tags": ["dev"]},
    {"id": "memory", "name": "Memory (knowledge graph)",
     "description": "A local knowledge-graph memory the agent can read and grow.",
     "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-memory"],
     "env_keys": [], "runtime": "node", "tags": ["memory", "official"]},
    {"id": "sequential-thinking", "name": "Sequential Thinking",
     "description": "A structured step-by-step reasoning scratchpad tool.",
     "transport": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-sequential-thinking"],
     "env_keys": [], "runtime": "node", "tags": ["reasoning", "official"]},
    {"id": "sqlite", "name": "SQLite",
     "description": "Query a local SQLite database. Point --db-path at your file.",
     "transport": "stdio", "command": "uvx",
     "args": ["mcp-server-sqlite", "--db-path", "~/data.db"],
     "env_keys": [], "runtime": "python", "tags": ["data", "official"]},
    {"id": "time", "name": "Time",
     "description": "Current time and timezone conversions.",
     "transport": "stdio", "command": "uvx", "args": ["mcp-server-time"],
     "env_keys": [], "runtime": "python", "tags": ["utility", "official"]},
    {"id": "playwright", "name": "Playwright (browser)",
     "description": "Drive a real browser: navigate, click, fill forms, screenshot.",
     "transport": "stdio", "command": "npx", "args": ["-y", "@playwright/mcp@latest"],
     "env_keys": [], "runtime": "node", "tags": ["web", "browser"]},
    {"id": "context7", "name": "Context7 (library docs)",
     "description": "Up-to-date documentation for programming libraries.",
     "transport": "stdio", "command": "npx", "args": ["-y", "@upstash/context7-mcp"],
     "env_keys": [], "runtime": "node", "tags": ["dev", "docs"]},
]


def list_directory() -> list[dict]:
    """The catalog (a copy, so callers can't mutate the module constant)."""
    return [dict(e) for e in DIRECTORY]
