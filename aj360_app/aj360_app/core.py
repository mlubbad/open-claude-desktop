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

# Pure, dependency-free helper re-exported for external call sites that still
# read it as core.fmt_bytes (agent.py / state.py). The BigQuery + schema-catalog
# code that used to consume these helpers now lives in
# ocd_core.{bigquery,schema_catalog}; fmt_bytes stays re-exported here.
from ocd_core.util import fmt_bytes  # noqa: E402,F401

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
# Read-only SQL guard — BANNED_ALIASES re-exported for agent.py's prompt text.
from ocd_core.sql_guard import BANNED_ALIASES  # noqa: E402,F401

# Structured observability: the local core._observe was behavior-identical to
# ocd_core.observability.observe (confirmed in a prior slice). Re-exported under
# the old private name so any lingering core._observe reference keeps working.
from ocd_core.observability import observe as _observe  # noqa: E402,F401

# BigQuery client + dry-run + read-only SQL execution moved into ocd_core.bigquery.
from ocd_core.bigquery import get_bq_client, execute_sql, _dry_run  # noqa: E402,F401

# Schema catalog (build / version-gate / semantic search) moved into
# ocd_core.schema_catalog. The private helpers stay re-exported under their old
# names so external surfaces (agent.py, state.py) keep working via core.X.
from ocd_core.schema_catalog import (  # noqa: E402,F401
    ensure_catalog, search_schema, _build_catalog_sync, _catalog_version_matches,
    _schema_catalog, _kb_documents,
)
