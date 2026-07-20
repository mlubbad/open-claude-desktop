# backend/ocd_core/harness/rules.py
"""Permission modes + allow/deny/ask rule engine (pure functions).

Modes: default | acceptEdits | plan | strict | bypass (legacy aliases auto->bypass,
ask->default). Rule precedence: deny > ask > allow > mode default.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from pathlib import Path

from .. import jsonstore

READ_ONLY_TOOLS = {"read_file", "glob", "grep"}
WRITE_TOOLS = {"edit_file", "write_file"}

_ALIASES = {"auto": "bypass", "ask": "default"}
_MODES = {"default", "acceptEdits", "plan", "strict", "bypass"}
# Bash commands auto-approved in acceptEdits (jailed cwd already constrains them).
SAFE_BASH = {"ls", "cat", "head", "tail", "wc", "echo", "pwd", "grep", "find",
             "sort", "uniq", "cut", "mkdir", "touch", "mv", "cp", "sed"}
# git is subcommand-gated in acceptEdits: only read-only subcommands auto-approve;
# push/commit/reset/rebase/clean etc. reach the network or destroy history -> they ask.
GIT_READONLY = {"status", "log", "diff", "show", "branch", "ls-files",
                "rev-parse", "blame", "remote"}


def _bash_auto_allowed(cmd: str) -> bool:
    """First-token allowlist for acceptEdits, with git gated by subcommand."""
    parts = cmd.split()
    if not parts:
        return False
    if parts[0] == "git":
        return len(parts) > 1 and parts[1] in GIT_READONLY
    return parts[0] in SAFE_BASH


def normalize_mode(mode: str | None) -> str:
    m = (mode or "default").strip()
    m = _ALIASES.get(m, m)
    return m if m in _MODES else "strict"  # unknown fails closed


def _parse(rule: str) -> tuple[str, str | None]:
    """'bash(git *)' -> ('bash', 'git *'); 'read_file' -> ('read_file', None)."""
    rule = rule.strip()
    if rule.endswith(")") and "(" in rule:
        name, matcher = rule[:-1].split("(", 1)
        return name.strip(), matcher.strip()
    return rule, None


def _arg_string(tool: str, args: dict) -> str:
    if tool == "bash":
        return str((args or {}).get("command", ""))
    return str((args or {}).get("path", "") or (args or {}).get("url", ""))


def _matches(rule: str, tool: str, args: dict) -> bool:
    name, matcher = _parse(rule)
    if name not in ("*", tool):
        return False
    if matcher is None or matcher == "*":
        return True
    return fnmatch.fnmatch(_arg_string(tool, args), matcher)


@dataclass
class RuleSet:
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    ask: list[str] = field(default_factory=list)

    def decision(self, tool: str, args: dict) -> str | None:
        """deny > ask > allow; None if no rule matches."""
        if any(_matches(r, tool, args) for r in self.deny):
            return "deny"
        if any(_matches(r, tool, args) for r in self.ask):
            return "ask"
        if any(_matches(r, tool, args) for r in self.allow):
            return "allow"
        return None


def gate(tool: str, args: dict, mode: str, ruleset: RuleSet) -> str:
    """Return 'allow' | 'deny' | 'ask' for a tool call. Rules win over mode defaults."""
    mode = normalize_mode(mode)
    ruled = ruleset.decision(tool, args)
    if ruled is not None:
        return ruled
    if mode == "bypass":
        return "allow"
    if mode == "plan":
        return "allow" if tool in READ_ONLY_TOOLS else "deny"
    if mode == "strict":
        return "ask"
    # default / acceptEdits
    if tool in READ_ONLY_TOOLS:
        return "allow"
    if tool in WRITE_TOOLS:
        return "allow" if mode == "acceptEdits" else "ask"
    if tool == "bash":
        cmd = str((args or {}).get("command", "")).strip()
        if mode == "acceptEdits" and _bash_auto_allowed(cmd):
            return "allow"
        return "ask"
    return "ask"  # unknown/sensitive tool


# Map Claude Code tool names to ours (best-effort; unmapped names pass through lowercased).
_CLAUDE_TOOL_MAP = {
    "Bash": "bash", "Read": "read_file", "Edit": "edit_file",
    "Write": "write_file", "Glob": "glob", "Grep": "grep", "WebFetch": "web_fetch",
}


def _map_rule(rule: str) -> str:
    name, matcher = _parse(rule)
    mapped = _CLAUDE_TOOL_MAP.get(name, name[:1].lower() + name[1:] if name else name)
    return f"{mapped}({matcher})" if matcher is not None else mapped


def load_claude_ruleset(workspace_root) -> RuleSet:
    """Read a workspace's .claude/settings.json permissions block into a RuleSet.
    Best-effort: any error yields an empty RuleSet (never raises)."""
    path = Path(workspace_root) / ".claude" / "settings.json"
    data = jsonstore.load_json(path, {})
    perms = data.get("permissions", {}) if isinstance(data, dict) else {}
    def conv(key):
        vals = perms.get(key, []) if isinstance(perms, dict) else []
        return [_map_rule(str(r)) for r in vals] if isinstance(vals, list) else []
    return RuleSet(allow=conv("allow"), deny=conv("deny"), ask=conv("ask"))
