"""Interactive `ocd` session — a dependency-free REPL over the same engine.

Streams each turn with the shared Renderer and supports a small set of slash-commands
(``/model``, ``/provider``, ``/effort``, ``/new``, ``/help``, ``/quit``). A ``/name`` that
isn't a known command falls through to the agent, where ``resolve_skill`` may match a
skill — so skills work here exactly as in the desktop composer.
"""
from __future__ import annotations

import asyncio
import sys

from .cli import _defaults, _drive, _persist

REPL_COMMANDS = {"help", "?", "model", "provider", "effort", "project",
                 "new", "clear", "quit", "exit"}

HELP = """\
Commands:
  /model <id>        switch model            /new            start a fresh conversation
  /provider <id>     switch provider         /project <id>   scope to a project ("" clears)
  /effort <level>    Low|Medium|High|Max     /help           show this help
  /quit              exit                    /<skill> …      run a skill (e.g. /summarize …)
Type a message and press Enter. Ctrl-D or /quit to exit."""


def parse_command(line: str) -> tuple[str, object]:
    """Classify a REPL line. Returns ("empty",""), ("cmd",(name,arg)), or ("chat",text).
    Only known slash-commands are treated as commands; other /names go to the agent."""
    line = line.strip()
    if not line:
        return ("empty", "")
    if line.startswith("/"):
        parts = line[1:].split(None, 1)
        name = (parts[0] or "").lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        if name in REPL_COMMANDS:
            return ("cmd", (name, arg))
    return ("chat", line)


class _Args:
    """A minimal args object for _drive (mirrors argparse fields it reads)."""

    def __init__(self, cfg: dict, project: str | None, no_color: bool) -> None:
        self.project = project
        self.no_color = no_color
        self.json = False
        self.no_tools = False


def run_repl(args) -> int:
    try:
        import readline  # noqa: F401 - line editing + history if available
    except Exception:
        pass

    cfg = _defaults(args)
    project = args.project
    no_color = bool(getattr(args, "no_color", False))
    history: list[dict] = []
    conv_id = None

    out = sys.stdout
    print(f"ocd {cfg['model']} · {cfg['provider']} · effort {cfg['effort']}  (/help, /quit)")
    while True:
        try:
            line = input("\n› ")
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        kind, payload = parse_command(line)
        if kind == "empty":
            continue
        if kind == "cmd":
            name, arg = payload  # type: ignore[misc]
            if name in ("quit", "exit"):
                return 0
            if name in ("help", "?"):
                print(HELP)
            elif name == "model" and arg:
                cfg["model"] = arg
                print(f"model → {arg}")
            elif name == "provider" and arg:
                cfg["provider"] = arg
                print(f"provider → {arg}")
            elif name == "effort" and arg in ("Low", "Medium", "High", "Max"):
                cfg["effort"] = arg
                print(f"effort → {arg}")
            elif name == "project":
                project = arg or None
                print(f"project → {project or '(none)'}")
            elif name in ("new", "clear"):
                history = []
                conv_id = None
                print("(new conversation)")
            else:
                print(f"(usage: /{name} <value> — see /help)")
            continue

        goal = str(payload)
        drive_args = _Args(cfg, project, no_color)
        answer, ok = asyncio.run(_drive(goal, history, cfg, drive_args, out))
        if ok and answer.strip():
            history.append({"role": "user", "content": goal})
            history.append({"role": "assistant", "content": answer})
            conv_id = _persist(project, conv_id, goal, answer)
    return 0
