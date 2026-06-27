"""BigQuery schema catalog: build, version-gate, and semantic search.

Moved verbatim from aj360_app/aj360_app/core.py (_schema_catalog, _kb_documents,
_catalog_version_matches, _build_catalog_sync, ensure_catalog, search_schema).
Behavior parity is the contract — only import references were adjusted:
  * ocd_core.chroma._get_chroma for the catalog/kb collections
  * ocd_core.bigquery.get_bq_client for the BigQuery client
  * util.flatten_fields in place of the old _flatten_fields alias
  * ocd_core.knowledge.search_project_kb for the isolated project KB
  * config.* for the constants core.py imported at module top
"""
from __future__ import annotations

from . import config, util
from .bigquery import get_bq_client
from .chroma import _get_chroma
from .knowledge import search_project_kb


# ---- ChromaDB catalog collections (shared with the Chainlit app) ----
def _schema_catalog():
    return _get_chroma().get_or_create_collection("schema_catalog")


def _kb_documents():
    return _get_chroma().get_or_create_collection("kb_documents")


# --------------------------------------------------------------------------- #
#  Schema catalog build (sync; callers wrap in asyncio.to_thread)
# --------------------------------------------------------------------------- #
def _catalog_version_matches() -> bool:
    try:
        return config._CATALOG_VERSION_FILE.exists() and \
            config._CATALOG_VERSION_FILE.read_text().strip() == config._CATALOG_VERSION
    except Exception:
        return False


def _build_catalog_sync() -> tuple[int, list[str]]:
    client = get_bq_client()
    catalog = _schema_catalog()
    tables, col_to_tables, errors = [], {}, []
    for ds in config.CATALOG_DATASETS:
        try:
            listing = list(client.list_tables(ds))
        except Exception as e:
            errors.append(f"{ds}: list failed ({e})")
            continue
        for item in listing:
            try:
                t = client.get_table(f"{config.PROJECT_ID}.{ds}.{item.table_id}")
            except Exception as e:
                errors.append(f"{ds}.{item.table_id}: get_table failed ({e})")
                continue
            cols = util.flatten_fields(t.schema)[:config.MAX_COLS_PER_CARD]
            tables.append((ds, item.table_id, t.table_type, t.num_rows, t.modified, cols))
            fq = f"{ds}.{item.table_id}"
            for cname, _, _ in cols:
                col_to_tables.setdefault(cname, set()).add(fq)

    ids, docs, metas = [], [], []
    for ds, tbl, ttype, nrows, modified, cols in tables:
        fq = f"{ds}.{tbl}"
        lines = [f"TABLE: `{config.PROJECT_ID}.{ds}.{tbl}`"]
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
            if cname in config.GENERIC_COLS or "." in cname:
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
        config._CATALOG_VERSION_FILE.write_text(config._CATALOG_VERSION)
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
