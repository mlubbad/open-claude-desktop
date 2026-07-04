"""BigQuery connector — the agent-facing surface (Phase 2).

Demotes BigQuery from the always-on agent core to an OPT-IN connector (owner
decision D2: the general assistant is the product). Its tool specs, its
system-prompt section, and its enablement flag live here; execution still lives in
``bigquery.py`` / ``schema_catalog.py``. When disabled, the agent never sees these
tools and its prompt carries no BigQuery/AJ360 content.

Enablement: ``BIGQUERY_ENABLED`` (explicit) else auto-on when a GCP project is
configured — so existing analytics deployments keep working unchanged while a fresh
install with no project is a pure general assistant.
"""
from __future__ import annotations

from . import config, sql_guard

SEARCH_SCHEMA_TOOL = {"type": "function", "function": {
    "name": "search_schema",
    "description": "Retrieve exact table names, columns, types, candidate join keys, "
                   "AND any relevant wiki / project-KB findings. ALWAYS call before "
                   "writing SQL.",
    "parameters": {"type": "object", "properties": {
        "question": {"type": "string", "description": "What you need schema for."}},
        "required": ["question"]}}}

RUN_SQL_TOOL = {"type": "function", "function": {
    "name": "run_sql",
    "description": "Validate (dry-run) and run a complete BigQuery standard-SQL SELECT. "
                   "Read-only: non-SELECT statements are rejected.",
    "parameters": {"type": "object", "properties": {
        "sql": {"type": "string", "description": "Full BigQuery standard-SQL query."}},
        "required": ["sql"]}}}

TOOL_SPECS = [SEARCH_SCHEMA_TOOL, RUN_SQL_TOOL]
TOOL_NAMES = frozenset(t["function"]["name"] for t in TOOL_SPECS)


def enabled() -> bool:
    return config.BIGQUERY_ENABLED


def system_prompt_section() -> str:
    """The BigQuery/AJ360 operating rules, injected only when the connector is on."""
    return f"""# BIGQUERY ANALYTICS (connector)
You can query Google BigQuery for the configured datasets. Project: \
`{config.PROJECT_ID}`  Region: EU. Dialect: BigQuery standard SQL.

You write and run SQL yourself. Operating loop:
1. Call `search_schema` to get EXACT table and column names AND check the knowledge wiki.
2. Write fully-qualified SQL using the EXACT table names from search_schema.
3. Call `run_sql`. If it returns an error, fix the SQL and retry.
4. When you have data, write the final answer with exact numbers in a Markdown table.

This connector is READ-ONLY: only SELECT runs. Do not attempt INSERT/UPDATE/DELETE/DDL.

Domain rules:
- Profile suspicious columns before trusting them.
- DATE vs TIMESTAMP: confirm from schema before comparing.
- Banned aliases: {', '.join(sorted(sql_guard.BANNED_ALIASES))}.
- Device: always `devicetype`, NEVER `device_category`.
- video_completion_rate is broken -> SAFE_DIVIDE workaround.
- Aggregate on series_id, NOT series_title.
- Default window: CURRENT_DATE() - 2.
- GA4 tables are huge: filter by stream_id + short window for UNNEST.
- Search funnels are separate per platform.

Be evidence-first: report exact numbers from query results, never estimates."""
