"""UI-agnostic slash-command parsing + skill resolution (salvaged from app.py
on_message, SALVAGE #5). Returns intents/text — never touches a UI session."""
from dataclasses import dataclass
from pathlib import Path

from . import skills as _skills

_EXACT = {
    "projects": {"/projects"},
    "skills": {"/skills"},
    "reload_skills": {"/reload-skills"},
}
_EXACT_MULTI = {"refresh_catalog": {"/refresh-catalog", "/rebuild-catalog"}}
# Prefix-matched commands. app.py uses `goal.lower().startswith(<prefix>)`:
#   - "/project " carries a TRAILING SPACE, so bare "/project" (or "/project "
#     after .strip()) never matches and falls through to skill matching.
#   - "/set-instructions", "/learn-finding", "/lint-knowledge" have no trailing
#     space, so they match both the bare command and "<cmd> <arg>".
_PREFIX = {
    "project": "/project ",
    "set_instructions": "/set-instructions",
    "learn_finding": "/learn-finding",
    "lint_knowledge": "/lint-knowledge",
}


@dataclass
class Command:
    name: str | None      # None => not a command (plain message)
    arg: str
    raw: str


def parse(text: str) -> Command:
    raw = (text or "").strip()
    low = raw.lower()
    for name, prefixes in {**_EXACT, **_EXACT_MULTI}.items():
        if low in prefixes:
            return Command(name=name, arg="", raw=raw)
    for name, prefix in _PREFIX.items():
        if low.startswith(prefix):
            return Command(name=name, arg=raw[len(prefix):].strip(), raw=raw)
    return Command(name=None, arg=raw, raw=raw)


def resolve_skill(text: str, skills_dir: Path | None = None,
                  filenames: list[str] | None = None) -> tuple[str, str, bool]:
    goal = (text or "").strip()
    available = _skills.list_skills(skills_dir)
    if goal.startswith("/"):
        low = goal.lower()
        for s in available:
            cmd = f"/{s['name']}".lower()
            if low == cmd or low.startswith(cmd + " "):
                rest = goal[len(cmd):].strip()
                return (rest or f"Run the {s['name']} skill.", s["name"], False)
    name = _skills.matching_skill(goal, skills_dir, filenames=filenames)
    return (goal, name, bool(name))
