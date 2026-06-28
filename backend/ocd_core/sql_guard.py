"""Read-only BigQuery SQL guard — single source of truth shared by the Chainlit
(app.py) and Reflex (aj360_app) surfaces.

Pure, framework-agnostic helpers that keep the agent's generated SQL safe:
  * is_mutation          — read-only-by-default classification (fail-safe)
  * tables_out_of_scope  — dataset-scope enforcement on parsed referenced_tables
  * tables_off_allowlist — per-project table allowlist (substring; KNOWN-WART)
  * check_banned_aliases — reject BigQuery reserved words used as bare aliases
"""
from __future__ import annotations

import re

# BigQuery reserved words that break queries when used as bare aliases.
BANNED_ALIASES = {
    "rows", "range", "groups", "current", "all", "order",
    "partition", "window", "over", "rollup", "hash",
}

# Words that legitimately follow ")" and are NOT aliases.
_KEYWORDS_AFTER_PAREN = {
    "select", "from", "where", "group", "order", "having", "limit",
    "union", "intersect", "except", "on", "and", "or", "not",
    "left", "right", "inner", "outer", "cross", "full", "join", "into",
}


def is_mutation(stmt: str | None) -> bool:
    """True for anything the BigQuery dry-run does NOT classify as a pure SELECT.
    Fail-safe: unknown/None counts as a mutation."""
    return (stmt or "").upper() != "SELECT"


def tables_out_of_scope(referenced, allowed: set, project_id: str = "") -> list:
    """Fully-qualified tables referenced by the query that fall outside the
    allowed ``<project>.<dataset>`` scopes. ``referenced`` is BigQuery's parsed
    referenced_tables list (each item exposes .project/.dataset_id/.table_id);
    ``project_id`` is only used as a fallback when an item lacks .project."""
    out = []
    for t in referenced or []:
        scope = f"{getattr(t, 'project', project_id)}.{getattr(t, 'dataset_id', '')}"
        if scope not in allowed:
            out.append(f"{scope}.{getattr(t, 'table_id', '?')}")
    return out


def tables_off_allowlist(sql: str, allowlist: list[str]) -> bool:
    """True if a non-empty allowlist is in force and NONE of its tables appear
    in the SQL. KNOWN-WART: substring match (faithful to app.py run_sql); should
    move to parsed referenced_tables in a later hardening pass."""
    if not allowlist:
        return False
    low = sql.lower()
    return not any(t.lower() in low for t in allowlist)


def check_banned_aliases(sql: str) -> "str | None":
    """Return an error string if the SQL uses a BigQuery reserved word as an
    alias (via ``AS x`` or a parenthesis alias), else None."""
    aliases = set()
    for m in re.finditer(r"\bAS\s+(\w+)", sql, re.IGNORECASE):
        aliases.add(m.group(1).lower())
    for m in re.finditer(r"\)\s+(\w+)", sql):
        word = m.group(1).lower()
        if word not in _KEYWORDS_AFTER_PAREN:
            aliases.add(word)
    hits = aliases & BANNED_ALIASES
    if hits:
        return (f"Banned alias(es) detected: {', '.join(sorted(hits))}. "
                f"BigQuery reserves these words. Full list: "
                f"{', '.join(sorted(BANNED_ALIASES))}")
    return None
