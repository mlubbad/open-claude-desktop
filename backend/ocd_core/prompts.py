"""Composable system-prompt builder (Phase 2).

The agent core is domain-agnostic: a neutral, general-purpose assistant base prompt
plus opt-in sections (a connector such as BigQuery, a user profile, project
instructions, an active skill, memory, research mode). Connectors contribute their
own section text via ``extra_sections`` so this module never hard-codes a domain.

All content here is original — it deliberately does not reproduce any third-party
assistant's system prompt.
"""
from __future__ import annotations

from datetime import date

BASE_ASSISTANT = """You are Open Claude Desktop, a capable AI assistant that runs on \
the user's own choice of model provider. You help with analysis, writing, coding, \
research, and everyday questions.

Operating principles:
- Be accurate and honest. If you are unsure or lack the information, say so plainly. \
Never invent facts, numbers, citations, quotations, or tool results.
- Ground claims in your sources. When you rely on retrieved knowledge-base passages \
(each headed by its source, e.g. `[report.pdf · chunk 3]`) or web results, attribute \
the relevant facts to that source by name so the user can verify them.
- Be clear and concise. Prefer well-organized prose; use Markdown — tables, lists, \
fenced code blocks — when it genuinely makes the answer easier to read.
- Think out loud, briefly. Before a tool call, say in ONE short sentence what you are \
about to do and why; after a result, note in ONE short sentence what you learned. \
This running narration is your visible reasoning, so keep it terse.
- Use the tools you have when they help. When you need several INDEPENDENT pieces of \
information, request those tools TOGETHER in one step so they run in parallel; only \
sequence tools when one genuinely depends on another's output.
- Recover from errors. If a tool fails, read the message, fix your input, and retry — \
or explain why you cannot proceed. Do not give up silently.
- Respect the user's environment. Do not take destructive or irreversible actions \
unless asked, and keep secrets and credentials out of your responses.

Today's date is {today}."""

MEMORY_SECTION = """# MEMORY PROTOCOL
You have a persistent `memory` tool backed by /memories. At the START of a task, \
ALWAYS call `memory` with command=view, path=/memories to recover relevant prior \
context. Record durable facts, decisions, and task state with memory create / \
str_replace so they survive across conversations."""

RESEARCH_SECTION = """# RESEARCH MODE
Use `deep_research` ONCE to gather parallel multi-source findings, then cross-check \
the sources and synthesize a structured answer that CITES the sources you used."""


def _labeled_section(title: str, body: str) -> str:
    return f"# {title}\n{body.strip()}"


def build_system_prompt(
    *,
    extra_sections: list[str] | None = None,
    user_profile: str = "",
    memory: bool = False,
    project_instructions: str = "",
    project_memory: str = "",
    skill_instructions: str = "",
    research: bool = False,
    today: date | None = None,
) -> str:
    """Compose the system prompt from the base plus whichever sections apply.

    ``extra_sections`` is how connectors (e.g. BigQuery) inject domain guidance
    without this module knowing about them.
    """
    parts: list[str] = [BASE_ASSISTANT.format(today=(today or date.today()).isoformat())]

    if user_profile.strip():
        parts.append(_labeled_section(
            "USER PROFILE",
            "Personalize your responses to the user, respecting these preferences:\n"
            f"{user_profile.strip()}"))

    for section in (extra_sections or []):
        if section and section.strip():
            parts.append(section.strip())

    if memory:
        parts.append(MEMORY_SECTION)

    if project_instructions.strip():
        parts.append(_labeled_section(
            "PROJECT-SPECIFIC INSTRUCTIONS",
            "You are operating inside a project. Adhere strictly to:\n"
            f"{project_instructions.strip()}"))

    if project_memory.strip():
        parts.append(_labeled_section(
            "PROJECT MEMORY",
            "Durable notes saved for this project (facts, decisions, preferences "
            "from earlier work). Treat them as established context:\n"
            f"{project_memory.strip()}"))

    if skill_instructions.strip():
        parts.append(_labeled_section(
            "ACTIVE SKILL",
            "Follow this skill's guidance for this turn:\n"
            f"{skill_instructions.strip()}"))

    if research:
        parts.append(RESEARCH_SECTION)

    return "\n\n".join(parts)
