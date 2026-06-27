"""
Open Claude Desktop backend core — Chainlit-free.

Extracted from the original Chainlit app.py so the Reflex UI can reuse the
exact same on-disk data: ./projects (registry + per-project instructions/KB),
./knowledge (wiki), ./chroma_db (vector store). Both apps stay data-compatible.

Only pure logic lives here (filesystem + ChromaDB + small helpers). BigQuery and
LLM agent integration are added in a later milestone.
"""
from __future__ import annotations

import os
import json
import time
import threading
from pathlib import Path

# --------------------------------------------------------------------------- #
#  Paths — resolve the repo root so we share data with the Chainlit app.
#  core.py lives at <repo>/aj360_app/aj360_app/core.py -> parents[2] == <repo>.
#  Override with AJ360_DATA_DIR if the layout ever changes.
# --------------------------------------------------------------------------- #
# Load the shared .env (ZHIPU_API_KEY, GCP_PROJECT_ID, …) from the repo root
# BEFORE importing ocd_core.config (which reads these env vars at import time).
_repo_root_for_env = Path(os.getenv("AJ360_DATA_DIR", str(Path(__file__).resolve().parents[2])))
try:
    from dotenv import load_dotenv
    load_dotenv(_repo_root_for_env / ".env")
except Exception:
    pass

# Single source of truth for env-driven configuration (de-dups app.py/core.py).
from ocd_core.config import (
    REPO_ROOT, PROJECTS_DIR, KNOWLEDGE_DIR, CHROMA_PATH, SKILLS_DIR, PLUGINS_DIR,
    PROJECT_ID, MAX_BYTES_BILLED, QUERY_TIMEOUT_SEC, MAX_RETURN_ROWS,
    MAX_STORED_ROWS, MAX_COLS_PER_CARD, MAX_TABLE_ROWS_UI, CATALOG_DATASETS,
    _CATALOG_VERSION, _CATALOG_VERSION_FILE, GENERIC_COLS, AGENT_MODEL,
    FLASH_MODEL, VISION_MODEL, GLM_MODELS, EFFORT_LEVELS, DEFAULT_SETTINGS,
    SETTINGS_FILE, PROJECT_CAPACITY_BYTES, CONV_MAX_MESSAGES, GENERAL_ID,
    GENERAL_NAME,
)  # noqa: E402

# Pure, dependency-free helpers shared with the FastAPI backend. Only the two
# still used by the schema-catalog / SQL-execution code remaining in this module
# are imported here (slugify/fmt_size/chunk_id/relative_time/format_date moved
# with the data domain into ocd_core.{projects,conversations,knowledge}).
from ocd_core.util import (  # noqa: E402
    fmt_bytes,
    flatten_fields as _flatten_fields,
)

PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------- #
#  Data domain (projects / conversations / knowledge) + small accessors moved
#  into ocd_core so the FastAPI backend and the Reflex frontend share one
#  implementation. Re-exported here under their original names so every existing
#  call site (core.create_project, core._get_chroma, core.get_llm_client, …)
#  keeps working unchanged. Behavior parity is the contract.
# --------------------------------------------------------------------------- #
from ocd_core.chroma import _get_chroma, get_project_kb_collection  # noqa: E402,F401
from ocd_core.llm import get_llm_client  # noqa: E402,F401
from ocd_core.projects import (  # noqa: E402,F401
    list_projects, get_project, create_project, delete_project,
    get_project_instructions, save_project_instructions, get_project_memory,
    save_project_memory, get_project_allowlist, project_capacity,
    project_card_view,
)
from ocd_core.conversations import (  # noqa: E402,F401
    create_conversation, get_conversation, save_conversation,
    set_conversation_title, set_conversation_pinned, move_conversation,
    delete_conversation, list_conversations, list_all_conversations,
    generate_conversation_title, migrate_legacy_chat_history,
)
from ocd_core.knowledge import (  # noqa: E402,F401
    list_project_files, save_uploaded_file, extract_text_from_file,
    ingest_file_to_kb, list_all_files, search_project_kb,
)

# --------------------------------------------------------------------------- #
#  Global app settings (Customize page)
#  (SETTINGS_FILE imported from ocd_core.config near the top of this module.)
# --------------------------------------------------------------------------- #
# Claude-style "Extended thinking" levels — each maps to real backend behaviour
# (steps cap + planning/verification passes + temperature) in agent.EFFORT.
EFFORT_DESCRIPTIONS = {
    "Low": "Fast, direct answers",
    "Medium": "A little more checking",
    "High": "Plans before answering",
    "Max": "Plans, then self-verifies",
}


def get_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    try:
        if SETTINGS_FILE.exists():
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # Backward-compat: older files stored "reasoning_level".
                if "effort" not in data and "reasoning_level" in data:
                    data["effort"] = data["reasoning_level"]
                s.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    except Exception:
        pass
    if s.get("effort") not in EFFORT_LEVELS:
        s["effort"] = "High"
    return s


def save_settings(values: dict) -> dict:
    s = get_settings()
    s.update({k: v for k, v in values.items() if k in DEFAULT_SETTINGS})
    try:
        SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
    except Exception:
        pass
    return s


# =========================================================================== #
#  BigQuery + schema catalog + SQL execution  (domain layer, UI-agnostic)
#  (PROJECT_ID, MAX_BYTES_BILLED, QUERY_TIMEOUT_SEC, MAX_*, CATALOG_DATASETS,
#   _CATALOG_VERSION[_FILE], GENERIC_COLS, VISION_MODEL imported from
#   ocd_core.config near the top of this module.)
# =========================================================================== #
# Read-only SQL guard — single source of truth shared with the Chainlit app.
from ocd_core.sql_guard import BANNED_ALIASES, check_banned_aliases  # noqa: E402,F401

_bq_client = None
_bq_lock = threading.Lock()


def _observe(event: str, **fields):
    try:
        import sys
        print(json.dumps({"event": event, **fields}, default=str), file=sys.stderr)
    except Exception:
        pass


def get_bq_client():
    global _bq_client
    with _bq_lock:
        if _bq_client is None:
            import google.auth
            from google.cloud import bigquery
            credentials, _ = google.auth.default()
            _bq_client = bigquery.Client(project=PROJECT_ID, credentials=credentials)
        return _bq_client


# ---- LLM client (ZhipuAI / GLM): get_llm_client now lives in ocd_core.llm and
# is re-exported at the top of this module. ----

# ---- ChromaDB catalog collections (shared with the Chainlit app) ----
# _schema_catalog / _kb_documents stay here until Task 8; they use the
# re-exported _get_chroma (from ocd_core.chroma) above.
def _schema_catalog():
    return _get_chroma().get_or_create_collection("schema_catalog")


def _kb_documents():
    return _get_chroma().get_or_create_collection("kb_documents")


# --------------------------------------------------------------------------- #
#  Schema catalog build (sync; callers wrap in asyncio.to_thread)
# --------------------------------------------------------------------------- #
def _catalog_version_matches() -> bool:
    try:
        return _CATALOG_VERSION_FILE.exists() and \
            _CATALOG_VERSION_FILE.read_text().strip() == _CATALOG_VERSION
    except Exception:
        return False


def _build_catalog_sync() -> tuple[int, list[str]]:
    client = get_bq_client()
    catalog = _schema_catalog()
    tables, col_to_tables, errors = [], {}, []
    for ds in CATALOG_DATASETS:
        try:
            listing = list(client.list_tables(ds))
        except Exception as e:
            errors.append(f"{ds}: list failed ({e})")
            continue
        for item in listing:
            try:
                t = client.get_table(f"{PROJECT_ID}.{ds}.{item.table_id}")
            except Exception as e:
                errors.append(f"{ds}.{item.table_id}: get_table failed ({e})")
                continue
            cols = _flatten_fields(t.schema)[:MAX_COLS_PER_CARD]
            tables.append((ds, item.table_id, t.table_type, t.num_rows, t.modified, cols))
            fq = f"{ds}.{item.table_id}"
            for cname, _, _ in cols:
                col_to_tables.setdefault(cname, set()).add(fq)

    ids, docs, metas = [], [], []
    for ds, tbl, ttype, nrows, modified, cols in tables:
        fq = f"{ds}.{tbl}"
        lines = [f"TABLE: `{PROJECT_ID}.{ds}.{tbl}`"]
        bits = [ttype or "TABLE"]
        if nrows is not None:
            bits.append(f"~{nrows:,} rows")
        if modified:
            bits.append(f"modified {modified.date()}")
        lines.append("(" + ", ".join(bits) + ")")
        lines.append("COLUMNS:")
        for cname, ctype, cmode in cols:
            tag = f" {cmode}" if cmode and cmode != "NULLABLE" else ""
            lines.append(f"- {cname} ({ctype}{tag})")
        joins = []
        for cname, _, _ in cols:
            if cname in GENERIC_COLS or "." in cname:
                continue
            partners = col_to_tables.get(cname, set()) - {fq}
            if 1 <= len(partners) <= 8:
                joins.append(f"{cname} -> [{', '.join(sorted(p.split('.')[1] for p in partners))}]")
        if joins:
            lines.append("CANDIDATE JOIN KEYS (shared columns, heuristic): " + "; ".join(joins[:15]))
        ids.append(fq)
        docs.append("\n".join(lines))
        metas.append({"dataset": ds, "table": tbl, "type": ttype or "TABLE"})
    for i in range(0, len(ids), 100):
        catalog.upsert(ids=ids[i:i + 100], documents=docs[i:i + 100], metadatas=metas[i:i + 100])
    try:
        _CATALOG_VERSION_FILE.write_text(_CATALOG_VERSION)
    except Exception:
        pass
    return len(ids), errors


def ensure_catalog() -> tuple[int, list[str]]:
    """Build the catalog only if missing/stale. Cheap when already built."""
    catalog = _schema_catalog()
    try:
        count = catalog.count()
    except Exception:
        count = 0
    if _catalog_version_matches() and count > 0:
        return count, []
    return _build_catalog_sync()


# --------------------------------------------------------------------------- #
#  search_schema — catalog + wiki + isolated project KB
#  (search_project_kb moved to ocd_core.knowledge and is re-exported at the top
#   of this module; search_schema below uses that re-exported name.)
# --------------------------------------------------------------------------- #
def search_schema(question: str, active_project: str | None = None, top_k: int = 6) -> str:
    blocks: list[str] = []
    try:
        cat = _schema_catalog().query(query_texts=[question], n_results=top_k)
        if cat.get("documents") and cat["documents"][0]:
            blocks.append("# Relevant tables\n\n" + "\n\n".join(cat["documents"][0]))
    except Exception as e:
        blocks.append(f"(schema search error: {e})")

    try:
        kb = _kb_documents()
        if kb.count() > 0:
            docs = kb.query(query_texts=[question], n_results=5)
            if docs.get("documents") and docs["documents"][0]:
                wiki_hits, doc_hits = [], []
                metas = docs.get("metadatas", [[]])[0]
                for doc, meta in zip(docs["documents"][0], metas):
                    if meta.get("type") == "wiki" or str(meta.get("source", "")).endswith(".md"):
                        wiki_hits.append(doc)
                    else:
                        doc_hits.append(doc)
                if wiki_hits:
                    blocks.append("# Knowledge Wiki (agent-maintained)\n\n"
                                  + "\n\n---\n\n".join(wiki_hits))
                if doc_hits:
                    blocks.append("# Notes from uploaded documents\n\n"
                                  + "\n---\n\n".join(doc_hits))
    except Exception:
        pass

    if active_project:
        proj = search_project_kb(active_project, question, top_k)
        if proj:
            blocks.append("# Project Knowledge Base (Isolated)\n\n" + proj)

    return "\n\n".join(blocks) if blocks else \
        "No catalog matches. The schema catalog may be empty; rebuild it first."


# --------------------------------------------------------------------------- #
#  SQL validation + execution (read-only analytics policy)
# --------------------------------------------------------------------------- #
# fmt_bytes moved to ocd_core.util (imported near the top of this module).
# _check_banned_aliases moved to ocd_core.sql_guard.check_banned_aliases
# (shared with the Chainlit app).


def _dry_run(sql: str):
    from google.cloud.bigquery import QueryJobConfig
    client = get_bq_client()
    try:
        job = client.query(sql, QueryJobConfig(dry_run=True, use_query_cache=False))
        stmt = getattr(job, "statement_type", None) or "UNKNOWN"
        return True, stmt, job.total_bytes_processed or 0, None
    except Exception as e:
        return False, None, 0, str(e)


def execute_sql(sql: str, active_project: str | None = None) -> dict:
    """Validate + run a query. Read-only policy: only SELECT executes.

    Returns a structured result:
      {ok, stmt, columns, rows, total_rows, truncated, bytes, agent_text, error}
    `agent_text` is what the LLM sees; `rows`/`columns` drive the UI table.
    """
    from google.cloud.bigquery import QueryJobConfig
    sql = (sql or "").strip()
    t0 = time.time()
    if not sql:
        return {"ok": False, "error": "empty", "agent_text": "No SQL provided."}

    if active_project:
        allow = get_project_allowlist(active_project)
        if allow and not any(tok.lower() in sql.lower() for tok in allow):
            return {"ok": False, "error": "allowlist",
                    "agent_text": f"SQL REJECTED: project allows only: {', '.join(allow)}"}

    alias_err = check_banned_aliases(sql)
    if alias_err:
        return {"ok": False, "error": "alias", "agent_text": f"SQL REJECTED: {alias_err}"}

    ok, stmt, est_bytes, err = _dry_run(sql)
    if not ok:
        return {"ok": False, "stmt": stmt, "error": err,
                "agent_text": f"VALIDATION FAILED (0 rows scanned). Fix and retry.\nError: {err}"}

    if stmt != "SELECT":
        return {"ok": False, "stmt": stmt, "error": "mutation_blocked",
                "agent_text": (f"REJECTED: {stmt} statements are disabled in the chat agent "
                               f"(read-only analytics). Rewrite as a SELECT.")}

    if est_bytes > MAX_BYTES_BILLED:
        return {"ok": False, "stmt": stmt, "error": "cost",
                "agent_text": (f"REFUSED: estimated scan {fmt_bytes(est_bytes)} exceeds the cap "
                               f"{fmt_bytes(MAX_BYTES_BILLED)}. Add partition/date filters.")}

    try:
        client = get_bq_client()
        job = client.query(sql, QueryJobConfig(maximum_bytes_billed=MAX_BYTES_BILLED))
        rows_iter = job.result(timeout=QUERY_TIMEOUT_SEC)
        billed = job.total_bytes_billed or job.total_bytes_processed or 0
        rows = []
        for r in rows_iter:
            rows.append(dict(r))
            if len(rows) >= MAX_STORED_ROWS:
                break
        total = rows_iter.total_rows if rows_iter.total_rows is not None else len(rows)
        truncated = total > len(rows)
        columns = list(rows[0].keys()) if rows else []
        preview = rows[:MAX_RETURN_ROWS]
        header = (f"[{total} rows; showing first {len(preview)}]"
                  if total > len(preview) else f"[{total} rows]")
        agent_text = f"{header} scanned {fmt_bytes(billed)}\n{json.dumps(preview, default=str)}"
        _observe("query_ok", rows=total, bytes=billed, latency_s=round(time.time() - t0, 2))
        return {"ok": True, "stmt": stmt, "columns": columns, "rows": rows,
                "total_rows": total, "truncated": truncated, "bytes": billed,
                "agent_text": agent_text}
    except Exception as e:
        _observe("query_fail", error=str(e))
        return {"ok": False, "stmt": stmt, "error": str(e),
                "agent_text": f"EXECUTION FAILED: {e}. Fix the SQL and try again."}
