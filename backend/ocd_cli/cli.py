"""`ocd` — the command-line front-end over ocd_core.

Drives ``agent.run_turn`` and renders the frozen event vocabulary in the terminal.
Two modes: headless ``ocd -p "prompt"`` (one shot; ``--json`` for machine output) and an
interactive REPL (``ocd`` with no prompt). Reuses the same engine, providers, BYOK keys,
skills, and persistence as the desktop app — no duplicate agent logic.
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from .render import Renderer, json_line

__version__ = "0.1.0"

GENERAL = "general"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="verso",
        description="VersoWork in your terminal — model-agnostic (BYOK).",
    )
    p.add_argument("prompt", nargs="*", help="The prompt. Omit for an interactive session.")
    p.add_argument("-p", "--print", dest="headless", action="store_true",
                   help="Headless: run one turn, print the result, and exit.")
    p.add_argument("--json", action="store_true",
                   help="Emit the raw event stream as JSONL (implies headless).")
    p.add_argument("-m", "--model", help="Model id (overrides the saved default).")
    p.add_argument("--provider", help="Provider id (else inferred from the model / default).")
    p.add_argument("-e", "--effort", choices=["Low", "Medium", "High", "Max"],
                   help="Reasoning effort (default from settings).")
    p.add_argument("--project", help="Project id to scope knowledge/instructions to.")
    p.add_argument("-c", "--continue", dest="cont", action="store_true",
                   help="Continue the most recent conversation.")
    p.add_argument("--resume", metavar="ID", help="Resume a conversation by id.")
    p.add_argument("--no-tools", action="store_true", help="Disable web search/fetch + artifacts.")
    p.add_argument("--no-color", action="store_true", help="Disable ANSI colour.")
    p.add_argument("--version", action="version", version=f"ocd {__version__}")
    return p


def _defaults(args) -> dict:
    """Resolve model/provider/effort, falling back to saved settings."""
    from ocd_core import settings
    s = settings.get_settings()
    return {
        "model": args.model or s.get("model"),
        "provider": args.provider or s.get("provider"),
        "effort": args.effort or s.get("effort") or "High",
    }


def _history_from(messages: list[dict]) -> list[dict]:
    """Prior turns as plain role/content pairs for run_turn."""
    out = []
    for m in messages or []:
        role = m.get("role")
        if role in ("user", "assistant"):
            out.append({"role": role, "content": m.get("content", "")})
    return out


def _load_conversation(args):
    """Return (project_id, conv_id, history) for --resume/--continue, else (None, None, [])."""
    from ocd_core import conversations as cv
    if args.resume:
        for c in cv.list_all_conversations(limit=1000):
            if c["id"] == args.resume:
                full = cv.get_conversation(c["project_id"], c["id"])
                return c["project_id"], c["id"], _history_from(full["messages"] if full else [])
        print(f"ocd: no conversation with id {args.resume}", file=sys.stderr)
        return None, None, []
    if args.cont:
        recent = cv.list_all_conversations(limit=1)
        if recent:
            c = recent[0]
            full = cv.get_conversation(c["project_id"], c["id"])
            return c["project_id"], c["id"], _history_from(full["messages"] if full else [])
    return None, None, []


async def _drive(goal: str, history: list[dict], cfg: dict, args, out) -> tuple[str, bool]:
    """Stream one turn to ``out``. Returns (answer_text, ok)."""
    from ocd_core import agent, commands, skills
    clean_goal, skill_name, _auto = commands.resolve_skill(goal)
    skill_instr = (skills.get_skill(skill_name) or {}).get("instructions", "") if skill_name else ""
    renderer = Renderer(color=not args.no_color)
    tools_on = not args.no_tools
    answer: list[str] = []
    ok = True
    async for ev in agent.run_turn(
        clean_goal, history, args.project, cfg["model"],
        effort=cfg["effort"], provider=cfg["provider"], permission_mode="auto",
        skill_instructions=skill_instr, web_search=tools_on, web_fetch=tools_on,
        artifacts=tools_on, memory=tools_on, subagents=tools_on,
    ):
        out.write(json_line(ev) if args.json else renderer.feed(ev))
        out.flush()
        if ev.get("type") == "delta" and ev.get("scope") == "answer":
            answer.append(ev.get("text", ""))
        if ev.get("type") == "error":
            ok = False
    if not args.json:
        out.write("\n")
    return "".join(answer), ok


def _persist(project_id, conv_id, goal, answer):
    """Best-effort save of the exchange so --continue/--resume can pick it up."""
    from ocd_core import conversations as cv
    from ocd_core.db import engine
    try:
        engine.init_db()
    except Exception:
        return conv_id
    try:
        pid = project_id or GENERAL
        if conv_id is None:
            conv = cv.create_conversation(pid, goal)
            conv_id = conv["id"]
            msgs = list(conv["messages"])
        else:
            full = cv.get_conversation(pid, conv_id)
            msgs = list(full["messages"]) if full else [{"role": "user", "content": goal, "kind": "user"}]
            if not (msgs and msgs[-1].get("role") == "user"):
                msgs.append({"role": "user", "content": goal, "kind": "user"})
        msgs.append({"role": "assistant", "content": answer, "kind": "final"})
        cv.save_conversation(pid, conv_id, msgs)
    except Exception as e:  # noqa: BLE001 - persistence is best-effort
        print(f"ocd: could not save conversation ({e})", file=sys.stderr)
    return conv_id


def run_headless(goal: str, args, out=None) -> int:
    """One-shot run. Returns a process exit code."""
    out = out or sys.stdout
    cfg = _defaults(args)
    project_id, conv_id, history = (None, None, [])
    if args.resume or args.cont:
        project_id, conv_id, history = _load_conversation(args)
    answer, ok = asyncio.run(_drive(goal, history, cfg, args, out))
    if ok and answer.strip():
        _persist(project_id, conv_id, goal, answer)
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.json:
        args.headless = True
    goal = " ".join(args.prompt).strip()

    if goal and (args.headless or not sys.stdin.isatty()):
        return run_headless(goal, args)
    if goal or args.headless:
        # A prompt with no TTY already handled above; a headless flag with no prompt errors.
        if not goal:
            print("ocd: -p/--print requires a prompt", file=sys.stderr)
            return 2
        return run_headless(goal, args)

    from .repl import run_repl
    return run_repl(args)


if __name__ == "__main__":
    raise SystemExit(main())
