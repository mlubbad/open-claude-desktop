"""Read-only BigQuery SQL guard — single source of truth shared by the Chainlit
(app.py) and Reflex (aj360_app) surfaces.

Pure, framework-agnostic helpers that keep the agent's generated SQL safe:
  * is_mutation          — read-only-by-default classification (fail-safe)
  * tables_out_of_scope  — dataset-scope enforcement on parsed referenced_tables
  * datasets_out_of_scope— dataset-scope enforcement on parsed "dataset.table" ids
  * tables_off_allowlist — per-project table allowlist (parsed referenced_tables)
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


def tables_off_allowlist(referenced_tables: list[str], allowlist: list[str]) -> bool:
    """True if a non-empty allowlist is in force and ANY referenced table is not
    in it. `referenced_tables` are qualified ids (e.g. "dataset.table") parsed from
    the BigQuery dry-run — not substrings — so commented/quoted names can't bypass.
    Empty allowlist => no restriction (all allowed)."""
    if not allowlist:
        return False
    allowed = {a.lower() for a in allowlist}
    refs = [t.lower() for t in (referenced_tables or [])]
    if not refs:
        return True  # allowlist in force but refs couldn't be resolved -> deny (fail-safe)
    return any(r not in allowed for r in refs)


def datasets_out_of_scope(referenced_tables, allowed_datasets) -> list:
    """Referenced tables whose dataset falls outside the allowed set.

    ``referenced_tables`` are qualified ids ("dataset.table" or, when project-
    qualified, "project.dataset.table") parsed from the BigQuery dry-run -- the
    exact strings ``ocd_core.bigquery._dry_run`` returns. ``allowed_datasets`` is
    the permitted dataset names (e.g. ``config.CATALOG_DATASETS``); matching is
    case-insensitive on the dataset component.

    An empty ``allowed_datasets`` means no scope is configured => unrestricted.
    A query that references no tables (e.g. ``SELECT 1``) reads no data and is in
    scope => ``[]`` (parity with ``tables_out_of_scope``)."""
    allowed = {d.strip().lower() for d in (allowed_datasets or []) if str(d).strip()}
    if not allowed:
        return []
    out = []
    for r in (referenced_tables or []):
        parts = str(r).split(".")
        dataset = parts[-2].lower() if len(parts) >= 2 else parts[0].lower()
        if dataset not in allowed:
            out.append(r)
    return out


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
