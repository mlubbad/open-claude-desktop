"""Skill builder — the agent-facing surface for authoring a skill in chat.

`create_artifact` can already produce a skill-shaped *document*, but a document is
not a skill: nothing writes it into SKILLS_DIR, so "build me a skill" ended at a
download button. This module adds the missing half — a `save_skill` tool that
persists what the model wrote, so it comes back as `/<name>` (and, with triggers, as
an auto-firing skill) in every later chat.

Gating: the tool is registered ONLY for a turn the user opened with `/skill-builder`
(see `commands.parse` → `app.routes.agent`). A saved skill is instructions that future
turns obey, so it must not be reachable from unattended runs or from tool output that
talks the model into writing one.
"""
from __future__ import annotations

import re

from . import skills
from .artifact_tools import strip_code_fence

# Frontmatter is line-oriented (`key: value`) and `triggers` is comma-split by the
# loader, so any newline or comma the model puts in a single-line field would swallow
# the fields after it. Normalize rather than reject — a good skill shouldn't fail to
# save over a stray comma.
_WS = re.compile(r"\s+")
_SLUG = re.compile(r"[^a-z0-9]+")

SAVE_SKILL_TOOL = {"type": "function", "function": {
    "name": "save_skill",
    "description": "Save a reusable skill so it persists across chats. The user invokes "
                   "it later as /<name>, and it fires automatically when a message "
                   "matches one of its triggers. Call this ONCE, at the end, with the "
                   "COMPLETE instructions — re-calling it with the same name replaces "
                   "the earlier version rather than creating a duplicate.",
    "parameters": {"type": "object", "properties": {
        "name": {"type": "string",
                 "description": "Short kebab-case name; becomes the /slash-command."},
        "description": {"type": "string",
                        "description": "One line, on its own, describing when to use "
                                       "the skill. Shown in the skills list."},
        "instructions": {"type": "string",
                         "description": "The COMPLETE skill body in Markdown — the "
                                        "procedure the model should follow when the "
                                        "skill runs. Raw source, no wrapping code "
                                        "fence, and no frontmatter (that is generated)."},
        "triggers": {"type": "array", "items": {"type": "string"},
                     "description": "Optional distinctive phrases that auto-fire the "
                                    "skill. Prefer specific multi-word phrases; a "
                                    "single common word will hijack unrelated chats."}},
        "required": ["name", "description", "instructions"]}}}

TOOL_SPECS = [SAVE_SKILL_TOOL]
TOOL_NAMES = frozenset(t["function"]["name"] for t in TOOL_SPECS)


def _one_line(text: str) -> str:
    return _WS.sub(" ", (text or "").replace(",", " ")).strip()


def slugify(name: str) -> str:
    return _SLUG.sub("-", (name or "").strip().lower()).strip("-")[:64]


def build_markdown(args: dict) -> str:
    """Render the tool arguments as a skill file the loader can read back."""
    name = slugify(args.get("name", ""))
    triggers = [t for t in (_one_line(t) for t in (args.get("triggers") or [])) if t]
    front = [f"name: {name}",
             f"description: {_one_line(args.get('description', '')) or 'Skill'}"]
    if triggers:
        front.append("auto: true")
        front.append(f"triggers: {', '.join(triggers)}")
    body = strip_code_fence((args.get("instructions") or "").strip())
    return "---\n" + "\n".join(front) + "\n---\n\n" + body.strip() + "\n"


def save(args: dict) -> dict:
    """Validate + persist. Returns {ok, name, created} or {ok: False, detail}."""
    name = slugify(args.get("name", ""))
    if not name:
        return {"ok": False, "detail": "a skill name is required"}
    if not strip_code_fence(args.get("instructions") or "").strip():
        return {"ok": False, "detail": "instructions are empty — send the full skill body"}
    return skills.save_skill(name, build_markdown(args))


def system_prompt_section() -> str:
    return """# SKILL BUILDER
The user asked you to build a SKILL: reusable instructions that persist across chats. \
Write it for a future model that will have none of this conversation's context.

1. Ground it first. A skill that names a table, column, endpoint, file, or API you have \
not verified this turn is worse than no skill — it will fail silently every time it \
runs. Look things up with the tools you have, and run the query or command once to \
prove it works. If you cannot verify something, say so in the skill instead of \
guessing.
2. Write the body as a procedure: when to use it, the exact steps, the verified \
commands/queries in full, the output format, and the traps that make naive attempts \
wrong. Prefer specifics over advice.
3. Save it with `save_skill` — ONE call, at the end, carrying the complete body. Do not \
put the skill in an artifact; an artifact cannot be invoked later. Choose `triggers` \
that are distinctive multi-word phrases; a broad single word will hijack unrelated \
chats, and no triggers at all is fine for a skill meant to be run on demand.
4. Then tell the user, in one or two lines, what it does and how to run it (`/<name>`, \
plus any trigger phrases)."""


BUILDER_BRIEF = ("Build a persistent skill for the request below, following the SKILL "
                 "BUILDER instructions, and save it with `save_skill`.\n\n")
