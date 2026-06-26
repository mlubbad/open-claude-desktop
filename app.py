"""
Open Claude Desktop — Semantic BigQuery Agent (v2.4.0)
========================================

Refactored from v2.3.2 — all review findings addressed:

Critical:
  - Static action callbacks (project edit/delete fully functional)
  - run_agent exceptions caught in _answer with user-visible feedback
  - Thread-safe registry with proper locking
  - Chart temp files deleted immediately after send

High:
  - stream_llm returns partial text on failure (no double API cost)
  - Content-hash based KB deduplication (_chunk_id)
  - on_chat_resume properly restores SQL hint from turn context
  - Word-boundary skill trigger matching (no false positives)
  - Content-hash based wiki invalidation (not mtime)
  - Catalog versioning on dataset config change

Medium:
  - Continuation token cap (prevents 16K+ token responses)
  - headroom compression failures logged
  - Stale catalog detection via version mismatch
  - Image context placed right after skill instructions
  - Per-user rate limiting on queries
  - Clear separation of _observe (real-time stderr) vs audit (persistent JSONL)

Low:
  - Lazy GCS private key loading
  - Named _StreamDone sentinel class
  - Configurable starters via STARTERS_FILE env var
  - Per-skill reference loading (references frontmatter field)
  - Skill disable via frontmatter (disabled: true)

Security:
  - Constant-time password comparison (hmac.compare_digest)
  - Project-level table allowlist support

Setup
-----
    pip install chainlit chromadb pandas pdfplumber google-cloud-bigquery zhipuai python-dotenv matplotlib
    pip install arabic_reshaper python-bidi   # optional, for Arabic chart labels
    gcloud auth application-default login
    .env: ZHIPU_API_KEY=...
    chainlit run app.py
"""

import os
import re
import json
import time
import uuid
import base64
import asyncio
import logging
import tempfile
import threading
import concurrent.futures
import hashlib
import hmac
import sys as _sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
import chainlit as cl
from chainlit.input_widget import Switch, Select

import pandas as pd
import pdfplumber

import chromadb
from google.cloud import bigquery
from google.cloud.bigquery import QueryJobConfig
import google.auth
from zhipuai import ZhipuAI

try:
    from headroom import compress
    HEADROOM_AVAILABLE = True
except ImportError:
    HEADROOM_AVAILABLE = False

load_dotenv()

# --------------------------------------------------------------------------- #
#  Configuration
# --------------------------------------------------------------------------- #
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "ajgc-dig-jjc-prod-jawacloud-01")

AGENT_MODEL = os.getenv("AGENT_MODEL", os.getenv("PLANNER_MODEL", "glm-4-plus"))
VISION_MODEL = os.getenv("VISION_MODEL", "glm-4v-plus")
# Cheap tier for low-complexity sub-tasks (e.g. /learn-finding structuring).
FLASH_MODEL = os.getenv("FLASH_MODEL", "glm-4-flash")

_glm_default = f"{AGENT_MODEL},glm-4.5-air,glm-4-flash,glm-4-long"
GLM_MODELS: list[str] = []
for _m in os.getenv("GLM_MODELS", _glm_default).split(","):
    _m = _m.strip()
    if _m and _m not in GLM_MODELS:
        GLM_MODELS.append(_m)


def _active_model() -> str:
    return cl.user_session.get("model") or AGENT_MODEL


RETRY_ACTION = "retry"


def _retry_actions(goal: str) -> list:
    return [cl.Action(name=RETRY_ACTION, payload={"goal": goal},
                      label="Retry", icon="refresh-cw",
                      tooltip="Regenerate this answer")]


GB = 1024 ** 3
MAX_BYTES_BILLED = int(float(os.getenv("MAX_BYTES_BILLED_GB", "100")) * GB)
CONFIRM_BYTES = int(float(os.getenv("CONFIRM_BYTES_GB", "50")) * GB)

CATALOG_DATASETS = [
    d.strip() for d in os.getenv(
        "CATALOG_DATASETS",
        "aj360,aj360_platform,aj360_search_analytics,"
        "al_jazeera_data_models,aj360_ds,aj360_monitoring,"
        "aj360_marts,aj360_acquisition_analytics",
    ).split(",") if d.strip()
]

# C2: agent is READ-ONLY by default; dataset scope is enforced at execution time
# against the engine's parsed table references (not fragile substring matching).
ALLOW_WRITES = os.getenv("AJ360_ALLOW_WRITES", "false").strip().lower() in ("true", "1", "yes")
ALLOWED_TABLE_SCOPES = {f"{PROJECT_ID}.{d}" for d in CATALOG_DATASETS}

MAX_RETURN_ROWS = 50
MAX_COLS_PER_CARD = 200
MAX_STORED_ROWS = 5000
QUERY_TIMEOUT_SEC = 300
MEMORY_TURNS = 12
AUDIT_LOG = "./logs/agent_audit.jsonl"
PDF_MAX_PAGES = 50
_HELPER_SENTINEL = "__HELPER__"

# Continuation cap — prevents 16K+ token responses
MAX_CONTINUATION_TOKENS = int(os.getenv("MAX_CONTINUATION_TOKENS", "6144"))

# Rate limiting
RATE_LIMIT_QUERIES = int(os.getenv("RATE_LIMIT_QUERIES", "20"))
RATE_LIMIT_WINDOW_SEC = int(os.getenv("RATE_LIMIT_WINDOW_SEC", "60"))

KNOWLEDGE_DIR = Path(os.getenv("KNOWLEDGE_DIR", "./knowledge"))
KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
(KNOWLEDGE_DIR / "dataset_notes").mkdir(exist_ok=True)
_WIKI_STATE_FILE = KNOWLEDGE_DIR / ".wiki_hash"
_CATALOG_VERSION_FILE = KNOWLEDGE_DIR / ".catalog_version"

SKILLS_DIR = Path(os.getenv("SKILLS_DIR", "./skills"))
SKILLS_DIR.mkdir(parents=True, exist_ok=True)

STARTERS_FILE = os.getenv("STARTERS_FILE", "")

_skills: dict = {}

# Catalog version — changes when CATALOG_DATASETS changes
_CATALOG_VERSION = hashlib.md5(
    ",".join(sorted(CATALOG_DATASETS)).encode()
).hexdigest()[:12]

# --------------------------------------------------------------------------- #
#  Observability
#
#  Two distinct systems with clear separation:
#  - _observe: Real-time structured JSON to stderr (debugging / monitoring)
#  - audit:    Persistent append-only JSONL trail (compliance / forensics)
# --------------------------------------------------------------------------- #
_logger = logging.getLogger("aj360_agent")
_logger.setLevel(logging.INFO)
_sh = logging.StreamHandler()
_sh.setFormatter(logging.Formatter("%(message)s"))
_logger.addHandler(_sh)


def _observe(event: str, **fields):
    """Emit a structured log record to stderr. Non-blocking, best-effort."""
    record = {"event": event, "ts": datetime.now(timezone.utc).isoformat(), **fields}
    _logger.info(json.dumps(record, default=str))


_AUDIT_LOCK = threading.Lock()


def audit(event: dict):
    """Append an event to the persistent audit trail (JSONL file). Thread-safe."""
    try:
        os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
        event = {"ts": datetime.now(timezone.utc).isoformat(), **event}
        with _AUDIT_LOCK:
            with open(AUDIT_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, default=str) + "\n")
    except Exception as e:
        print(f"[AUDIT] write failed: {e} | event={event.get('event')}",
              file=_sys.stderr)


try:
    os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
    with open(AUDIT_LOG, "a", encoding="utf-8"):
        pass
except Exception as _audit_err:
    print(f"[AUDIT] WARNING: audit log not writable ({AUDIT_LOG}): {_audit_err}",
          file=_sys.stderr)

# --------------------------------------------------------------------------- #
#  Rate Limiting
# --------------------------------------------------------------------------- #
_rate_limiter_lock = threading.Lock()
_user_query_times: dict[str, list[float]] = {}


def _check_rate_limit(user_id: str) -> bool:
    """Sliding-window rate limiter. Returns True if allowed, False if blocked."""
    now = time.time()
    with _rate_limiter_lock:
        times = _user_query_times.get(user_id, [])
        times = [t for t in times if now - t < RATE_LIMIT_WINDOW_SEC]
        if len(times) >= RATE_LIMIT_QUERIES:
            return False
        times.append(now)
        _user_query_times[user_id] = times
        return True


# --------------------------------------------------------------------------- #
#  Lazy GCS Key (Issue #17 — don't hold key in memory if unused)
# --------------------------------------------------------------------------- #
_gcs_private_key_cache: str | None = None
_gcs_key_loaded = False


def _get_gcs_private_key() -> str | None:
    global _gcs_private_key_cache, _gcs_key_loaded
    if not _gcs_key_loaded:
        raw = os.getenv("GCS_PRIVATE_KEY", "")
        if raw:
            _gcs_private_key_cache = raw if "\n" in raw else raw.replace("\\n", "\n")
        _gcs_key_loaded = True
    return _gcs_private_key_cache


# --------------------------------------------------------------------------- #
#  BigQuery Client
# --------------------------------------------------------------------------- #
_bq_client = None
_bq_lock = threading.Lock()
_catalog_lock = asyncio.Lock()
_query_semaphore = asyncio.Semaphore(3)
_query_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="bq_query")


def get_bq_client():
    global _bq_client
    with _bq_lock:
        if _bq_client is None:
            # C1: credentials come ONLY from Application Default Credentials
            # (Workload Identity / metadata server / `gcloud auth application-default
            # login`). No service-account key file is read from the project tree.
            try:
                credentials, _ = google.auth.default()
            except Exception as e:
                raise RuntimeError(
                    "No Google credentials found via ADC. On GCP use Workload Identity; "
                    "locally run `gcloud auth application-default login`. "
                    "Do NOT place a service-account key file in the repo."
                ) from e
            _bq_client = bigquery.Client(project=PROJECT_ID, credentials=credentials)
        return _bq_client


# --------------------------------------------------------------------------- #
#  ChromaDB Collections
# --------------------------------------------------------------------------- #
chroma = chromadb.PersistentClient(path="./chroma_db")
schema_catalog = chroma.get_or_create_collection("schema_catalog")
kb_documents = chroma.get_or_create_collection("kb_documents")

GENERIC_COLS = {
    "date", "name", "value", "type", "key", "status", "id", "count", "total",
    "country", "city", "region", "month", "week", "weekday", "source", "medium",
    "device", "category", "title", "description", "label", "url", "hour", "day",
}
BANNED_ALIASES = {"rows", "range", "groups", "current", "all", "order",
                  "partition", "window", "over", "rollup", "hash"}


# --------------------------------------------------------------------------- #
#  Projects Module — Thread-Safe (Issue #3)
# --------------------------------------------------------------------------- #
PROJECTS_DIR = Path(os.getenv("PROJECTS_DIR", "./projects"))
PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
_REGISTRY_FILE = PROJECTS_DIR / "_registry.json"
_REGISTRY_LOCK = threading.Lock()


def _slugify(text: str) -> str:
    slug = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
    return slug or "untitled"


def _load_registry() -> list:
    with _REGISTRY_LOCK:
        if _REGISTRY_FILE.exists():
            try:
                return json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                _observe("registry_corrupt", error=str(e))
                return []
        return []


def _save_registry(data: list):
    with _REGISTRY_LOCK:
        tmp = _REGISTRY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(_REGISTRY_FILE)  # Atomic on POSIX


def list_projects() -> list:
    return _load_registry()


def create_project(name: str) -> dict:
    projects = _load_registry()
    project_id = _slugify(name)

    existing_ids = {p["id"] for p in projects}
    if project_id in existing_ids:
        project_id = f"{project_id}-{uuid.uuid4().hex[:4]}"

    proj_dir = PROJECTS_DIR / project_id
    (proj_dir / "knowledge").mkdir(parents=True, exist_ok=True)

    instructions_path = proj_dir / "instructions.md"
    if not instructions_path.exists():
        instructions_path.write_text(
            f"# Instructions for {name}\n\nAdd specific guidelines for this project here.\n",
            encoding="utf-8")

    project_meta = {
        "id": project_id,
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    projects.append(project_meta)
    _save_registry(projects)

    _observe("project_created", project_id=project_id, name=name)
    return project_meta


def delete_project(project_id: str) -> bool:
    projects = _load_registry()
    updated = [p for p in projects if p["id"] != project_id]

    if len(updated) == len(projects):
        return False

    _save_registry(updated)

    proj_dir = PROJECTS_DIR / project_id
    if proj_dir.exists():
        import shutil
        shutil.rmtree(proj_dir)

    try:
        chroma.delete_collection(f"kb_project_{project_id}")
    except Exception:
        pass

    _observe("project_deleted", project_id=project_id)
    return True


def get_project_instructions(project_id: str) -> str:
    path = PROJECTS_DIR / project_id / "instructions.md"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def save_project_instructions(project_id: str, content: str):
    path = PROJECTS_DIR / project_id / "instructions.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def get_project_allowlist(project_id: str) -> list:
    """Returns table allowlist for a project, or empty list (all tables allowed)."""
    path = PROJECTS_DIR / project_id / "allowlist.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def get_project_kb_collection(project_id: str):
    return chroma.get_or_create_collection(f"kb_project_{project_id}")


# --------------------------------------------------------------------------- #
#  Content-Hash Chunk ID (Issue #6 — upload deduplication)
# --------------------------------------------------------------------------- #
def _chunk_id(filename: str, idx: int, content: str) -> str:
    h = hashlib.sha256(f"{filename}:{idx}:{content[:500]}".encode()).hexdigest()[:20]
    return f"{filename}_{idx}_{h}"


async def ingest_to_project(project_id: str, elements, step) -> int:
    total = 0
    collection = get_project_kb_collection(project_id)

    for el in elements:
        mime = el.mime or ""
        if mime.startswith("image"):
            with open(el.path, "rb") as fh:
                b64 = base64.b64encode(fh.read()).decode("utf-8")
            resp = await asyncio.to_thread(
                llm_client.chat.completions.create,
                model=VISION_MODEL,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": "Describe this image in detail for later retrieval."},
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime or 'image/png'};base64,{b64}"}}]}])
            text = resp.choices[0].message.content
        else:
            step.output = f"Reading {el.name}..."
            await step.update()
            text = await asyncio.to_thread(extract_text_from_file, el.path, mime)

        chunks = [text[i:i + 2000] for i in range(0, len(text), 2000)]
        for i in range(0, len(chunks), 20):
            batch = chunks[i:i + 20]
            # Content-hash IDs → re-uploads upsert instead of duplicate
            ids = [_chunk_id(f"{project_id}_{el.name}", i + j, batch[j])
                   for j in range(len(batch))]
            metas = [{"source": el.name, "chunk": i + j, "type": "project_upload",
                      "project_id": project_id}
                     for j in range(len(batch))]
            await asyncio.to_thread(
                collection.upsert, documents=batch, metadatas=metas, ids=ids)
            total += len(batch)
            step.output = f"Ingesting {el.name}... {total}/{len(chunks)} chunks."
            await step.update()
    return total


async def search_project_kb(project_id: str, question: str, top_k: int = 5) -> str:
    collection = get_project_kb_collection(project_id)
    try:
        if await asyncio.to_thread(collection.count) > 0:
            docs = await asyncio.to_thread(
                collection.query, query_texts=[question], n_results=top_k)
            if docs.get("documents") and docs["documents"][0]:
                return "\n\n---\n\n".join(docs["documents"][0])
    except Exception:
        pass
    return ""


# --------------------------------------------------------------------------- #
#  Image Processing
# --------------------------------------------------------------------------- #
async def _process_images(elements, step=None) -> str:
    descriptions = []
    for el in elements:
        mime = el.mime or ""
        if not mime.startswith("image"):
            continue
        try:
            with open(el.path, "rb") as fh:
                b64 = base64.b64encode(fh.read()).decode("utf-8")
            if step:
                step.output = f"Analyzing {el.name}..."
                await step.update()
            resp = await asyncio.to_thread(
                llm_client.chat.completions.create,
                model=VISION_MODEL,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": (
                        "Describe this image in detail. If it contains charts, "
                        "dashboards, tables, or data visualisations, describe the "
                        "metrics, axes, values, and any text labels you can read. "
                        "If it shows a UI or form, describe the fields and content. "
                        "Be thorough and precise — your description will be used by "
                        "a BigQuery analytics agent to answer the user's question.")},
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime};base64,{b64}"}}
                ]}])
            desc = resp.choices[0].message.content or "(could not describe image)"
            descriptions.append(f"**Image: {el.name}**\n{desc}")
        except Exception as e:
            descriptions.append(f"**Image: {el.name}** — Failed to process: {e}")
            _observe("image_process_fail", name=el.name, error=str(e))
    return "\n\n".join(descriptions)


# --------------------------------------------------------------------------- #
#  Knowledge Wiki — Content-Hash Invalidation (Issue #9)
# --------------------------------------------------------------------------- #
_SEED_WIKI = {
    "data_issues.md": """\
# AJ360 Data Issues & Gotchas

Auto-maintained by the agent. Add findings with `/learn-finding <description>`.

## Known Issues

### video_completion_rate is broken
- **Column**: `video_completion_rate`
- **Problem**: Values exceed 5000 (should be 0–100%). Likely a pipeline bug.
- **Workaround**: `SAFE_DIVIDE(duration_sec, NULLIF(content_duration, 0)) * 100`
- **Discovered**: Pre-loaded from v1 domain knowledge

### devicetype vs device_category
- **Problem**: `device_category` is ~43% TV-contaminated for mobile users
- **Workaround**: Always segment by `devicetype` (curated) or `devicetype` event param (raw GA4)
- **Discovered**: Pre-loaded from v1 domain knowledge

### series_title freezes at event time
- **Problem**: `series_title` is denormalized at event time, never backfilled, carries RTL marks
- **Workaround**: Aggregate on `series_id`. For Arabic titles use `LIKE '%word%'`
- **Discovered**: Pre-loaded from v1 domain knowledge

### Mobile search_results_click is dead
- **Problem**: `search_results_click` for Mobile/TV has not fired since ~Oct 2025
- **Workaround**: Exclude from funnel calculations for Mobile/TV
- **Discovered**: Pre-loaded from v1 domain knowledge
""",
    "query_patterns.md": """\
# AJ360 Common Query Patterns

Verified SQL patterns go here. Add them via `/learn-finding` after confirming
the query runs green in BigQuery. DO NOT add guessed or unverified SQL.

## Patterns

(No verified patterns yet. Run a query successfully, then use
`/learn-finding <description and SQL>` to persist it here.)
""",
    "aj360_rules.md": """\
# AJ360 Analysis Rules

Living document of rules the agent must follow. Extended via `/learn-finding`.

## SQL Rules
1. Default window: `CURRENT_DATE() - 2` (today/yesterday partitions can be incomplete)
2. Always fully-qualify tables: check `search_schema` for exact names in backticks
3. Profile suspicious columns: `SELECT COUNTIF(col IS NULL), APPROX_COUNT_DISTINCT(col) FROM <table>`
4. Column named `date` is usually DATE — compare with `CURRENT_DATE()`, confirm from schema

## Cost Rules
5. GA4 app tables are very large — filter by stream_id + short window (1d apps, 5-7d web) for UNNEST
6. Table sizes: `SELECT FROM <dataset>.__TABLES__` — `INFORMATION_SCHEMA.TABLE_STORAGE` does not exist

## Segment Rules
7. Search funnels are separate: Web (dot-notation), Mobile/TV (underscore) — never compare CTR across
8. Device: always `devicetype` — NEVER `device.category` / `device_category`
""",
}


def _seed_wiki_if_empty():
    for name, content in _SEED_WIKI.items():
        path = KNOWLEDGE_DIR / name
        if not path.exists():
            try:
                path.write_text(content, encoding="utf-8")
                _observe("wiki_seed", file=name)
            except Exception as e:
                _observe("wiki_seed_fail", file=name, error=str(e))


def _wiki_content_hash() -> str:
    """Hash file CONTENTS (not mtime) to avoid false re-ingest on touch/sync."""
    parts = []
    for md_path in sorted(KNOWLEDGE_DIR.rglob("*.md")):
        content = md_path.read_text(encoding="utf-8")
        h = hashlib.md5(content.encode()).hexdigest()
        parts.append(f"{md_path.relative_to(KNOWLEDGE_DIR)}:{h}:{len(content)}")
    return hashlib.md5("|".join(parts).encode()).hexdigest()


def _ingest_wiki_sync():
    _seed_wiki_if_empty()
    current_hash = _wiki_content_hash()
    if _WIKI_STATE_FILE.exists():
        try:
            if _WIKI_STATE_FILE.read_text().strip() == current_hash:
                return 0, 0, True
        except Exception:
            pass

    total = 0
    md_files = sorted(KNOWLEDGE_DIR.rglob("*.md"))
    for md_path in md_files:
        text = md_path.read_text(encoding="utf-8")
        rel = str(md_path.relative_to(KNOWLEDGE_DIR)).replace("\\", "/")
        chunks = []
        current_header = f"# {rel}"
        current_body: list[str] = []
        for line in text.split("\n"):
            if line.startswith("## ") or line.startswith("### "):
                if current_body:
                    chunks.append((f"{current_header}\n" + "\n".join(current_body)).strip())
                current_header = line
                current_body = []
            else:
                current_body.append(line)
        if current_body:
            chunks.append((f"{current_header}\n" + "\n".join(current_body)).strip())
        if not chunks:
            chunks = [text[:2000]]
        try:
            kb_documents.delete(where={"source": rel})
        except Exception:
            pass
        ids, docs, metas = [], [], []
        for i, chunk in enumerate(chunks):
            if not chunk.strip():
                continue
            for k, sub in enumerate(chunk[j:j + 2000] for j in range(0, len(chunk), 2000)):
                ids.append(f"wiki:{rel}:{i}:{k}")
                docs.append(sub)
                metas.append({"source": rel, "type": "wiki", "chunk_index": i,
                              "updated": datetime.now(timezone.utc).isoformat()})
        if ids:
            for b in range(0, len(ids), 100):
                kb_documents.upsert(ids=ids[b:b + 100], documents=docs[b:b + 100],
                                    metadatas=metas[b:b + 100])
            total += len(ids)
    _WIKI_STATE_FILE.write_text(current_hash)
    return total, len(md_files), False


async def ingest_wiki():
    return await asyncio.to_thread(_ingest_wiki_sync)


def _append_finding_to_wiki(finding: str, category: str = "data_issues") -> str:
    path = KNOWLEDGE_DIR / f"{category}.md"
    if not path.exists():
        path.write_text(f"# {category.replace('_', ' ').title()}\n\n", encoding="utf-8")
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"\n\n### Finding — {ts}\n{finding}\n- **Discovered by**: Agent (auto-logged)\n"
    path.write_text(path.read_text(encoding="utf-8") + entry, encoding="utf-8")
    try:
        _WIKI_STATE_FILE.unlink()
    except Exception:
        pass
    _observe("wiki_finding", category=category, finding=finding[:200])
    return str(path)


def _lint_wiki_sync() -> dict:
    results: dict = {"files": [], "issues": [], "suggestions": []}
    for md_path in sorted(KNOWLEDGE_DIR.rglob("*.md")):
        rel = str(md_path.relative_to(KNOWLEDGE_DIR))
        text = md_path.read_text(encoding="utf-8")
        age_days = (time.time() - md_path.stat().st_mtime) / 86400
        results["files"].append({"path": rel, "age_days": round(age_days, 1),
                                  "sections": len(re.findall(r'^## ', text, re.MULTILINE)),
                                  "bytes": md_path.stat().st_size})
        for sec in re.split(r'^## ', text, flags=re.MULTILINE)[1:]:
            header = sec.split("\n", 1)[0].strip()
            body = sec.split("\n", 1)[1].strip() if "\n" in sec else ""
            if len(body) < 20:
                results["issues"].append(f"{rel}: Section '{header}' is empty or stub")
        if age_days > 90:
            results["issues"].append(f"{rel}: Not updated in {age_days:.0f} days — may be stale")
    for ds in CATALOG_DATASETS:
        if not (KNOWLEDGE_DIR / "dataset_notes" / f"{ds}.md").exists():
            results["suggestions"].append(f"No dataset notes for `{ds}` — consider adding {ds}.md")
    return results


# --------------------------------------------------------------------------- #
#  Schema Catalog — Versioned (Issue #10)
# --------------------------------------------------------------------------- #
def _catalog_version_matches() -> bool:
    if _CATALOG_VERSION_FILE.exists():
        try:
            return _CATALOG_VERSION_FILE.read_text().strip() == _CATALOG_VERSION
        except Exception:
            pass
    return False


def _write_catalog_version():
    try:
        _CATALOG_VERSION_FILE.write_text(_CATALOG_VERSION)
    except Exception as e:
        _observe("catalog_version_write_fail", error=str(e))


def _flatten_fields(fields, prefix=""):
    out = []
    for f in fields:
        name = f"{prefix}{f.name}"
        mode = f.mode or "NULLABLE"
        out.append((name, f.field_type, mode))
        if f.field_type == "RECORD" and f.fields:
            out.extend(_flatten_fields(f.fields, prefix=name + "."))
    return out


def _build_catalog_sync():
    client = get_bq_client()
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
            all_cols = _flatten_fields(t.schema)
            if len(all_cols) > MAX_COLS_PER_CARD:
                _observe("catalog_truncate", table=f"{ds}.{item.table_id}",
                         total_cols=len(all_cols), kept=MAX_COLS_PER_CARD)
            cols = all_cols[:MAX_COLS_PER_CARD]
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
        schema_catalog.upsert(ids=ids[i:i + 100], documents=docs[i:i + 100], metadatas=metas[i:i + 100])
    return len(ids), errors


async def ensure_catalog(progress_step=None):
    async with _catalog_lock:
        # Issue #13: check version AND count, not just count==0
        version_ok = _catalog_version_matches()
        try:
            count = await asyncio.to_thread(schema_catalog.count)
        except Exception:
            count = 0

        if version_ok and count > 0:
            return count, []

        if progress_step:
            reason = "version mismatch" if not version_ok and count > 0 else "empty"
            progress_step.output = (
                f"Building schema catalog ({reason}) from BigQuery metadata "
                f"({', '.join(CATALOG_DATASETS)})... runs once.")
            await progress_step.update()

        n, errors = await asyncio.to_thread(_build_catalog_sync)
        _write_catalog_version()

        if progress_step:
            msg = f"Catalog built: {n} tables indexed."
            if errors:
                msg += f" {len(errors)} skipped (no access / not found)."
            progress_step.output = msg
            await progress_step.update()
        return n, errors


async def rebuild_catalog():
    global schema_catalog
    async with _catalog_lock:
        try:
            await asyncio.to_thread(chroma.delete_collection, "schema_catalog")
        except Exception:
            pass
        schema_catalog = chroma.get_or_create_collection("schema_catalog")
        n, errors = await asyncio.to_thread(_build_catalog_sync)
        _write_catalog_version()
        return n, errors


# --------------------------------------------------------------------------- #
#  Tool: search_schema
# --------------------------------------------------------------------------- #
async def search_schema(question: str, top_k: int = 6) -> str:
    blocks = []
    for attempt in range(2):
        try:
            cat = await asyncio.to_thread(
                schema_catalog.query, query_texts=[question], n_results=top_k)
            if cat.get("documents") and cat["documents"][0]:
                blocks.append("# Relevant tables\n\n" + "\n\n".join(cat["documents"][0]))
            break
        except Exception as e:
            if attempt == 0:
                await asyncio.sleep(1)
                continue
            blocks.append(f"(schema search error after retry: {e})")

    try:
        if await asyncio.to_thread(kb_documents.count) > 0:
            docs = await asyncio.to_thread(
                kb_documents.query, query_texts=[question], n_results=5)
            if docs.get("documents") and docs["documents"][0]:
                wiki_hits, doc_hits = [], []
                metas = docs.get("metadatas", [[]])[0]
                for doc, meta in zip(docs["documents"][0], metas):
                    if meta.get("type") == "wiki" or meta.get("source", "").endswith(".md"):
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

    active_project = cl.user_session.get("active_project")
    if active_project:
        try:
            proj_kb = get_project_kb_collection(active_project)
            if await asyncio.to_thread(proj_kb.count) > 0:
                proj_docs = await asyncio.to_thread(
                    proj_kb.query, query_texts=[question], n_results=top_k)
                if proj_docs.get("documents") and proj_docs["documents"][0]:
                    blocks.append("# Project Knowledge Base (Isolated)\n\n"
                                  + "\n\n---\n\n".join(proj_docs["documents"][0]))
        except Exception:
            pass

    return "\n\n".join(blocks) if blocks else \
        "No catalog matches. Catalog may be empty; ask the user to run /refresh-catalog."


# --------------------------------------------------------------------------- #
#  Tool: validate + run SQL
# --------------------------------------------------------------------------- #
async def _dry_run(sql: str):
    client = get_bq_client()
    cfg = QueryJobConfig(dry_run=True, use_query_cache=False)
    try:
        job = await asyncio.to_thread(client.query, sql, cfg)
        stmt = getattr(job, "statement_type", None) or "UNKNOWN"
        # C2: BigQuery parses the real tables the query touches — use this for scope
        # enforcement instead of substring matching on the SQL text.
        referenced = list(getattr(job, "referenced_tables", []) or [])
        return True, stmt, job.total_bytes_processed or 0, None, referenced
    except Exception as e:
        return False, None, 0, str(e), []


def _fmt_bytes(n):
    if n == 0:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024


def _check_banned_aliases(sql: str):
    aliases = set()
    for m in re.finditer(r'\bAS\s+(\w+)', sql, re.IGNORECASE):
        aliases.add(m.group(1).lower())
    _sql_keywords_after_paren = {
        'select', 'from', 'where', 'group', 'order', 'having', 'limit',
        'union', 'intersect', 'except', 'on', 'and', 'or', 'not',
        'left', 'right', 'inner', 'outer', 'cross', 'full', 'join', 'into'}
    for m in re.finditer(r'\)\s+(\w+)', sql):
        word = m.group(1).lower()
        if word not in _sql_keywords_after_paren:
            aliases.add(word)
    hits = aliases & BANNED_ALIASES
    if hits:
        return (f"Banned alias(es) detected: {', '.join(sorted(hits))}. "
                f"BigQuery reserves these words. Full list: {', '.join(sorted(BANNED_ALIASES))}")
    return None


def _is_mutation(stmt: str | None) -> bool:
    """Anything the BigQuery dry-run does NOT classify as a pure SELECT is treated
    as a mutation. Fail-safe: unknown/None counts as a mutation."""
    return (stmt or "").upper() != "SELECT"


def _tables_out_of_scope(referenced, allowed: set) -> list:
    """Fully-qualified tables the query references that fall outside the allowed
    `<project>.<dataset>` scopes. `referenced` is BigQuery's parsed
    referenced_tables list (each item exposes .project/.dataset_id/.table_id)."""
    out = []
    for t in referenced or []:
        scope = f"{getattr(t, 'project', PROJECT_ID)}.{getattr(t, 'dataset_id', '')}"
        if scope not in allowed:
            out.append(f"{scope}.{getattr(t, 'table_id', '?')}")
    return out


async def run_sql(sql: str, step) -> str:
    sql = sql.strip()
    t0 = time.time()

    # Issue #15: Rate limiting
    user = cl.user_session.get("user")
    user_id = getattr(user, "identifier", None) or "anonymous"
    if not _check_rate_limit(user_id):
        audit({"event": "rate_limited", "user": user_id, "sql": sql[:200]})
        return (f"RATE LIMITED: Too many queries in the last {RATE_LIMIT_WINDOW_SEC}s. "
                f"Limit is {RATE_LIMIT_QUERIES} queries. Please wait and try again.")

    # Issue #23: Project table allowlist
    active_project = cl.user_session.get("active_project")
    if active_project:
        allowlist = get_project_allowlist(active_project)
        if allowlist:
            if not any(t.lower() in sql.lower() for t in allowlist):
                audit({"event": "allowlist_block", "project": active_project, "sql": sql[:200]})
                return (f"SQL REJECTED: No allowed table found. "
                        f"Allowed tables for this project: {', '.join(allowlist)}")

    alias_error = _check_banned_aliases(sql)
    if alias_error:
        audit({"event": "banned_alias", "sql": sql})
        _observe("banned_alias", sql=sql[:200])
        return f"SQL REJECTED: {alias_error}"

    ok, stmt, est_bytes, error, referenced = await _dry_run(sql)
    if not ok:
        audit({"event": "validate_fail", "sql": sql, "error": error})
        return (f"VALIDATION FAILED (no rows scanned). Fix the SQL and try again.\n"
                f"Error: {error}")

    # C2: read-only by default — block any non-SELECT unless writes are explicitly
    # enabled. This runs BEFORE the human approval prompt below (defense in depth).
    if _is_mutation(stmt) and not ALLOW_WRITES:
        audit({"event": "mutation_blocked_readonly", "stmt": stmt, "sql": sql[:200]})
        _observe("mutation_blocked_readonly", stmt=stmt)
        return (f"REJECTED: this agent is read-only. '{stmt}' statements are disabled. "
                f"(Set AJ360_ALLOW_WRITES=true only if writes are explicitly intended.)")

    # C2: enforce dataset scope using the engine's PARSED references — not substring
    # matching. Catches forbidden tables even when joined alongside allowed ones.
    out_of_scope = _tables_out_of_scope(referenced, ALLOWED_TABLE_SCOPES)
    if out_of_scope:
        audit({"event": "dataset_scope_block", "sql": sql[:200], "tables": out_of_scope})
        _observe("dataset_scope_block", tables=out_of_scope[:10])
        return ("REJECTED: query references tables outside the permitted datasets: "
                f"{', '.join(sorted(set(out_of_scope))[:10])}. "
                f"Allowed scopes: {', '.join(sorted(ALLOWED_TABLE_SCOPES))}.")

    if stmt != "SELECT":
        res = await cl.AskActionMessage(
            content=f"⚠️ **{stmt}** statement requested (will modify data/objects). Approve?",
            actions=[cl.Action(name="run", payload={"value": "run"}, label="✅ Run"),
                     cl.Action(name="reject", payload={"value": "reject"}, label="❌ Reject")],
            timeout=300).send()
        if not res or res.get("payload", {}).get("value") == "reject":
            audit({"event": "mutation_rejected", "stmt": stmt, "sql": sql})
            return f"User rejected the {stmt} statement. Do not retry it."

    if est_bytes > MAX_BYTES_BILLED:
        audit({"event": "cost_refused", "sql": sql, "est_bytes": est_bytes})
        return (f"REFUSED: estimated scan {_fmt_bytes(est_bytes)} exceeds the cap "
                f"{_fmt_bytes(MAX_BYTES_BILLED)}. Add partition/date filters or narrow "
                f"columns, then retry.")
    if est_bytes > CONFIRM_BYTES:
        res = await cl.AskActionMessage(
            content=f"This query will scan ~**{_fmt_bytes(est_bytes)}**. Run it?",
            actions=[cl.Action(name="run", payload={"value": "run"}, label="✅ Run"),
                     cl.Action(name="reject", payload={"value": "reject"}, label="❌ Cancel")],
            timeout=300).send()
        if not res or res.get("payload", {}).get("value") == "reject":
            audit({"event": "cost_cancelled", "sql": sql, "est_bytes": est_bytes})
            return "User cancelled the query before execution (cost). Do not retry without narrowing it."

    step.output += f"\n\n_running ({stmt}, ~{_fmt_bytes(est_bytes)})_"
    await step.update()

    async with _query_semaphore:
        client = get_bq_client()
        cfg = QueryJobConfig(maximum_bytes_billed=MAX_BYTES_BILLED)
        job = None
        try:
            job = await asyncio.to_thread(client.query, sql, cfg)
            loop = asyncio.get_running_loop()
            rows_iter = await loop.run_in_executor(
                _query_executor, lambda: job.result(timeout=QUERY_TIMEOUT_SEC))
            billed = job.total_bytes_billed or job.total_bytes_processed or 0

            if stmt in ("INSERT", "UPDATE", "DELETE", "MERGE"):
                audit({"event": "dml_ok", "stmt": stmt, "sql": sql, "job_id": job.job_id,
                       "rows_affected": job.num_dml_affected_rows,
                       "latency_s": round(time.time() - t0, 2)})
                _observe("dml_ok", stmt=stmt, job_id=job.job_id,
                         rows_affected=job.num_dml_affected_rows,
                         latency_s=round(time.time() - t0, 2))
                return f"OK. Rows affected: {job.num_dml_affected_rows}."
            if stmt != "SELECT":
                audit({"event": "ddl_ok", "stmt": stmt, "sql": sql, "job_id": job.job_id})
                _observe("ddl_ok", stmt=stmt, job_id=job.job_id)
                return f"OK. {stmt} executed."

            total_rows_hint = rows_iter.total_rows
            rows = []
            for r in rows_iter:
                rows.append(dict(r))
                if len(rows) >= MAX_STORED_ROWS:
                    break
            total = total_rows_hint if total_rows_hint is not None else len(rows)
            truncated = total > len(rows)

            cl.user_session.set("last_result", {
                "sql": sql, "rows": rows,
                "columns": list(rows[0].keys()) if rows else [],
                "total_rows": total, "truncated": truncated})
            cl.user_session.set("last_query_meta", {
                "stmt": stmt, "total_rows": total, "bytes": billed})

            if rows:
                try:
                    shown = min(len(rows), 2000)
                    df_ui = pd.DataFrame(rows[:2000])
                    note = f" (showing {shown:,} of {total:,})" if total > shown else ""
                    await cl.Message(
                        content=f"📄{_HELPER_SENTINEL} Result{note}",
                        elements=[cl.Dataframe(data=df_ui, display="inline", name="results")]).send()
                except Exception:
                    pass

            preview = rows[:MAX_RETURN_ROWS]
            header = (f"[{total} rows; showing first {len(preview)}]"
                      if total > len(preview) else f"[{total} rows]")
            if truncated:
                header += f" [session/chart capped at {MAX_STORED_ROWS}]"

            audit({"event": "select_ok", "sql": sql, "job_id": job.job_id, "rows": total,
                   "stored_rows": len(rows), "bytes_billed": billed,
                   "latency_s": round(time.time() - t0, 2)})
            _observe("query_ok", job_id=job.job_id, rows=total, bytes=billed,
                     latency_s=round(time.time() - t0, 2))
            step.output += f"\n\n✅ {header}, scanned {_fmt_bytes(billed)}."
            await step.update()
            return f"{header}\n{json.dumps(preview, default=str)}"

        except Exception as e:
            if job is not None and getattr(job, "job_id", None):
                try:
                    await asyncio.to_thread(client.cancel_job, job.job_id)
                except Exception:
                    pass
            audit({"event": "execute_fail", "sql": sql, "error": str(e),
                   "latency_s": round(time.time() - t0, 2)})
            _observe("query_fail", error=str(e), latency_s=round(time.time() - t0, 2))
            return f"EXECUTION FAILED: {e}. Fix the SQL and try again."


# --------------------------------------------------------------------------- #
#  Tool: visualize
# --------------------------------------------------------------------------- #
def _arabicize(labels):
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return [get_display(arabic_reshaper.reshape(s)) for s in labels]
    except Exception:
        return labels


def _render_chart(rows, spec):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    df = pd.DataFrame(rows)
    ctype = (spec.get("chart_type") or "bar").lower()
    x = spec.get("x")
    y = spec.get("y")
    agg = (spec.get("agg") or "none").lower()
    top_n = spec.get("top_n")
    title = spec.get("title") or ""

    g = None
    series = None
    labels = None

    if ctype == "hist":
        if x not in df.columns:
            raise ValueError(f"x column '{x}' not in {list(df.columns)}")
        series = pd.to_numeric(df[x], errors="coerce").dropna()
    else:
        if x not in df.columns:
            raise ValueError(f"x column '{x}' not in {list(df.columns)}")
        if agg in ("sum", "mean", "min", "max") and y and y in df.columns:
            df[y] = pd.to_numeric(df[y], errors="coerce")
            g = df.groupby(x, dropna=False)[y].agg(agg).reset_index()
        elif agg == "count":
            g = df.groupby(x, dropna=False).size().reset_index(name="count")
            y = "count"
        else:
            if not y or y not in df.columns:
                raise ValueError(f"y column '{y}' not in {list(df.columns)}; or pass agg='count'")
            df[y] = pd.to_numeric(df[y], errors="coerce")
            g = df[[x, y]].dropna()
        if top_n:
            g = g.sort_values(y, ascending=False).head(int(top_n))
        labels = _arabicize(g[x].astype(str).tolist())

    fig, ax = plt.subplots(figsize=(9, 5))
    if ctype == "bar":
        ax.bar(range(len(g)), g[y]); ax.set_xticks(range(len(g)))
        ax.set_xticklabels(labels, rotation=45, ha="right"); ax.set_ylabel(y)
    elif ctype == "line":
        ax.plot(range(len(g)), g[y], marker="o"); ax.set_xticks(range(len(g)))
        ax.set_xticklabels(labels, rotation=45, ha="right"); ax.set_ylabel(y)
    elif ctype == "scatter":
        ax.scatter(pd.to_numeric(g[x], errors="coerce"), g[y])
        ax.set_xlabel(x); ax.set_ylabel(y)
    elif ctype == "pie":
        ax.pie(g[y], labels=labels, autopct="%1.1f%%")
    elif ctype == "hist":
        ax.hist(series, bins=int(spec.get("bins", 30)))
        ax.set_xlabel(x); ax.set_ylabel("frequency")
    else:
        raise ValueError(f"unsupported chart_type '{ctype}'")
    ax.set_title(title or f"{ctype} of {y or x}")
    fig.tight_layout()
    path = os.path.join(tempfile.gettempdir(), f"chart_{uuid.uuid4().hex}.png")
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)

    summary = (g.to_string(index=False) if g is not None
               else f"n={series.count()}, mean={series.mean():.2f}, "
                    f"min={series.min():.2f}, max={series.max():.2f}")
    return path, summary[:2000]


# --------------------------------------------------------------------------- #
#  File Ingest — Content-Hash Deduplication (Issue #6)
# --------------------------------------------------------------------------- #
def extract_text_from_file(file_path: str, mime_type: str) -> str:
    if "pdf" in mime_type or file_path.endswith(".pdf"):
        text = ""
        with pdfplumber.open(file_path) as pdf:
            pages = pdf.pages[:PDF_MAX_PAGES]
            for page in pages:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
            if len(pdf.pages) > PDF_MAX_PAGES:
                _observe("pdf_truncated", file=file_path,
                         total_pages=len(pdf.pages), extracted_pages=PDF_MAX_PAGES)
        return text
    if "csv" in mime_type or file_path.endswith(".csv"):
        df = pd.read_csv(file_path)
        return "\n\n".join([
            f"CSV with {len(df):,} rows and {len(df.columns)} columns.",
            "Columns: " + ", ".join(f"{c} ({df[c].dtype})" for c in df.columns),
            "Sample rows:\n" + df.head(20).to_string(index=False),
            "Numeric summary:\n" + df.describe(include="all").to_string(),
        ])
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


async def ingest_files(elements, step) -> int:
    total = 0
    for el in elements:
        mime = el.mime or ""
        if mime.startswith("image"):
            with open(el.path, "rb") as fh:
                b64 = base64.b64encode(fh.read()).decode("utf-8")
            resp = await asyncio.to_thread(
                llm_client.chat.completions.create,
                model=VISION_MODEL,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": "Describe this image in detail for later retrieval."},
                    {"type": "image_url",
                     "image_url": {"url": f"data:{mime or 'image/png'};base64,{b64}"}}]}])
            text = resp.choices[0].message.content
        else:
            step.output = f"Reading {el.name}..."
            await step.update()
            text = await asyncio.to_thread(extract_text_from_file, el.path, mime)
        chunks = [text[i:i + 2000] for i in range(0, len(text), 2000)]
        for i in range(0, len(chunks), 20):
            batch = chunks[i:i + 20]
            # Content-hash IDs → re-uploads upsert instead of creating duplicates
            ids = [_chunk_id(el.name, i + j, batch[j]) for j in range(len(batch))]
            metas = [{"source": el.name, "chunk": i + j, "type": "upload"}
                     for j in range(len(batch))]
            await asyncio.to_thread(
                kb_documents.upsert, documents=batch, metadatas=metas, ids=ids)
            total += len(batch)
            step.output = f"Ingesting {el.name}... {total}/{len(chunks)} chunks."
            await step.update()
    return total


# --------------------------------------------------------------------------- #
#  Skills — Word-Boundary Triggers, Disable, Per-Skill Refs (Issues #8, #21, #22)
# --------------------------------------------------------------------------- #
class Skill:
    def __init__(self, name, description, instructions,
                 auto=False, triggers=None, file_triggers=None,
                 references=None, disabled=False):
        self.name = name
        self.description = description or ""
        self.instructions = instructions or ""
        self.auto = bool(auto)
        self.triggers = [t for t in (triggers or []) if t]
        self.file_triggers = [t for t in (file_triggers or []) if t]
        self.references = [t for t in (references or []) if t]
        self.disabled = bool(disabled)

    def matches_text(self, text: str) -> bool:
        """Issue #8: Word-boundary matching to prevent false positives."""
        if not self.auto or not self.triggers:
            return False
        low = text.lower()
        return any(re.search(r'\b' + re.escape(t.lower()) + r'\b', low)
                   for t in self.triggers)

    def matches_files(self, elements) -> bool:
        if not self.auto or not self.file_triggers:
            return False
        for el in elements or []:
            name = (getattr(el, "name", "") or "").lower()
            for trig in self.file_triggers:
                if trig.lower() in name:
                    return True
        return False


def _load_skills() -> dict:
    """Load every `skills/*.md` file with optional YAML-style frontmatter:
    ---
    name: hero-slides
    description: Build hero-slide click reports
    auto: true
    triggers: hero, slide, carousel
    file_triggers: hero, slide
    references: bq_recipes, output_format
    disabled: false
    ---
    <instructions the agent will see when the skill matches>
    """
    out: dict = {}
    if not SKILLS_DIR.is_dir():
        return out
    for md_path in sorted(SKILLS_DIR.glob("*.md")):
        try:
            raw = md_path.read_text(encoding="utf-8")
        except Exception as e:
            _observe("skill_load_fail", name=md_path.name, error=str(e))
            continue

        name = md_path.stem
        description = ""
        instructions = raw.strip()
        auto = False
        triggers: list = []
        file_triggers: list = []
        references: list = []
        disabled = False

        m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", raw, re.DOTALL)
        if m:
            front, instructions = m.group(1), m.group(2).strip()
            for line in front.splitlines():
                if ":" not in line:
                    continue
                k, _, v = line.partition(":")
                k, v = k.strip().lower(), v.strip()
                if k == "name":
                    name = v
                elif k == "description":
                    description = v
                elif k == "auto":
                    auto = v.lower() in ("true", "yes", "1")
                elif k == "triggers":
                    triggers = [t.strip() for t in v.split(",") if t.strip()]
                elif k == "file_triggers":
                    file_triggers = [t.strip() for t in v.split(",") if t.strip()]
                elif k == "references":
                    references = [t.strip() for t in v.split(",") if t.strip()]
                elif k == "disabled":
                    disabled = v.lower() in ("true", "yes", "1")
        else:
            description = (raw.split("\n", 1)[0].lstrip("# ").strip())[:200]

        # Issue #22: Skip disabled skills
        if disabled:
            _observe("skill_disabled", name=name)
            continue

        out[name] = Skill(name, description, instructions,
                          auto=auto, triggers=triggers,
                          file_triggers=file_triggers,
                          references=references)
    _observe("skills_loaded", count=len(out), names=list(out))
    return out


# --------------------------------------------------------------------------- #
#  Agent
# --------------------------------------------------------------------------- #
TOOLS = [
    {"type": "function", "function": {
        "name": "search_schema",
        "description": "Retrieve exact table names, columns, types, candidate join keys, "
                       "AND any relevant wiki findings. ALWAYS call before writing SQL.",
        "parameters": {"type": "object", "properties": {
            "question": {"type": "string", "description": "What you need schema for."}},
            "required": ["question"]}}},
    {"type": "function", "function": {
        "name": "run_sql",
        "description": "Validate (dry-run) and run a complete BigQuery SQL string.",
        "parameters": {"type": "object", "properties": {
            "sql": {"type": "string", "description": "Full BigQuery standard-SQL query."}},
            "required": ["sql"]}}},
    {"type": "function", "function": {
        "name": "visualize",
        "description": "Render a chart from the rows returned by the most recent run_sql SELECT.",
        "parameters": {"type": "object", "properties": {
            "chart_type": {"type": "string", "enum": ["bar", "line", "scatter", "pie", "hist"]},
            "x": {"type": "string", "description": "Column for x axis / categories / histogram values."},
            "y": {"type": "string", "description": "Numeric column for y. Omit if agg='count'."},
            "agg": {"type": "string", "enum": ["sum", "mean", "min", "max", "count", "none"],
                    "description": "Aggregate y grouped by x."},
            "top_n": {"type": "integer", "description": "Keep the top N x-values by y."},
            "bins": {"type": "integer", "description": "Histogram bins."},
            "title": {"type": "string"}},
            "required": ["chart_type", "x"]}}},
]

SYSTEM_PROMPT = f"""You are a BigQuery analytics agent for the AJ360 (Al Jazeera 360) OTT platform.
Project: `{PROJECT_ID}`  Region: EU. Dialect: BigQuery standard SQL.

You write and run SQL yourself. Operating loop:
1. Call `search_schema` to get EXACT table and column names AND check the knowledge wiki.
2. Write fully-qualified SQL using the EXACT table names from search_schema.
3. Call `run_sql`. If it returns an error, fix the SQL and retry.
4. If a chart clarifies the result, call `visualize`.
5. When you have data, write the final answer with exact numbers in a table.

If the user has uploaded images, you will receive descriptions of those images in
your context. Use them to understand what the user is asking about — e.g. if they
show a dashboard screenshot, identify the metrics and tables needed to replicate
or explain the data.

**Compounding Knowledge**: When you discover a new data issue or useful query
pattern, suggest the user run `/learn-finding <description>` to persist it.

Hard rules (AJ360-specific):
- Profile suspicious columns before trusting them.
- DATE vs TIMESTAMP: confirm from schema before comparing.
- Banned aliases: {', '.join(sorted(BANNED_ALIASES))}.
- Device: always `devicetype`, NEVER `device_category`.
- video_completion_rate is broken → SAFE_DIVIDE workaround.
- Aggregate on series_id, NOT series_title.
- Default window: CURRENT_DATE() - 2.
- GA4 tables are huge: filter by stream_id + short window for UNNEST.
- Table sizes: SELECT FROM <dataset>.__TABLES__.
- Search funnels are separate per platform.
- Mobile search_results_click dead since ~Oct 2025.

Be terse, evidence-first, American English. Exact numbers.
"""

# Issue #19: Named sentinel class for clarity
class _StreamDone:
    __slots__ = ()

    def __repr__(self):
        return "<STREAM_DONE>"

_STREAM_DONE = _StreamDone()


# --------------------------------------------------------------------------- #
#  Shared agent-turn runner
# --------------------------------------------------------------------------- #
async def _answer(goal: str, skill_instructions: str = ""):
    memory = cl.user_session.get("memory") or []
    settings = cl.user_session.get("chat_settings")

    proj_instructions = ""
    active_project = cl.user_session.get("active_project")
    if active_project:
        proj_instructions = get_project_instructions(active_project)
        async with cl.Step(name="Project Context Loaded 🗂️") as proj_step:
            proj_step.output = (f"Active Project: `{active_project}`\n\n"
                                f"**Custom Instructions:**\n{proj_instructions}")
            await proj_step.update()

    # Issue #14: skill_instructions prepended FIRST, then image/doc context,
    # then user goal — so image context is right after skill instructions.
    if skill_instructions:
        goal = f"{skill_instructions}\n\n{goal}"

    # Issue #10/#13: Check catalog version, not just count
    try:
        needs_rebuild = not _catalog_version_matches()
        count = await asyncio.to_thread(schema_catalog.count)
        empty = count == 0
    except Exception:
        needs_rebuild = True
        empty = True

    if needs_rebuild or empty:
        async with cl.Step(name="Building schema catalog 📚") as step:
            await ensure_catalog(step)

    async with cl.Step(name=f"Agent ({_active_model()}) 🧠") as step:
        step.output = ""
        # Issue #2: Wrap run_agent in try/except for user-visible error
        try:
            result = await run_agent(goal, memory, settings, step, proj_instructions)
            if not isinstance(result, tuple) or len(result) != 3:
                result = ("An unexpected error occurred in the agent loop.", True, {})
            final_answer, already_sent, turn_context = result
        except Exception as e:
            _observe("run_agent_crash", error=str(e), goal=goal[:200])
            final_answer = f"❌ Agent error: {e}"
            already_sent = False
            turn_context = {}

        if not isinstance(final_answer, str):
            final_answer = str(final_answer)

        step.output += f"\n\n**Final Answer:**\n{final_answer}"

    if not already_sent:
        await cl.Message(content=final_answer,
                         actions=_retry_actions(goal)).send()

    memory.append({"role": "user", "content": goal})
    context_str = ""
    if turn_context and (turn_context.get("sqls_run")
                         or turn_context.get("schema_queries")):
        compact = {k: v for k, v in turn_context.items() if v}
        context_str = f"\n\n[Turn context: {json.dumps(compact, default=str)}]"
    memory.append({"role": "assistant", "content": (final_answer or "") + context_str})
    cl.user_session.set("memory", memory[-MEMORY_TURNS:])


async def stream_llm(messages, msg, **kw):
    """Stream LLM response. Issue #5: On failure, return partial text instead
    of making a second API call (which doubles cost)."""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()
    finish_reason = None

    def worker():
        nonlocal finish_reason
        try:
            for chunk in llm_client.chat.completions.create(
                    messages=messages, stream=True, **kw):
                try:
                    choice = chunk.choices[0]
                    if choice.finish_reason:
                        finish_reason = choice.finish_reason
                    delta = choice.delta.content
                except Exception:
                    delta = None
                if delta:
                    loop.call_soon_threadsafe(queue.put_nowait, delta)
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, RuntimeError(str(e)))
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, _STREAM_DONE)

    task = loop.run_in_executor(None, worker)

    parts: list[str] = []
    while True:
        item = await queue.get()
        if item is _STREAM_DONE:
            break
        if isinstance(item, Exception):
            # Issue #5: If we have partial text, return it — don't double API cost
            partial = "".join(parts)
            if partial:
                finish_reason = "error"
                # Don't overwrite — partial text is already streamed to user
                return partial, "error"
            # Only make a new call if we got absolutely nothing
            try:
                resp = await asyncio.to_thread(
                    llm_client.chat.completions.create, messages=messages, **kw)
                text = resp.choices[0].message.content or ""
                finish_reason = resp.choices[0].finish_reason
                msg.content = text
                await msg.update()
                return text, finish_reason
            except Exception as inner_e:
                finish_reason = "error"
                msg.content = f"[Stream failed: {item}, fallback failed: {inner_e}]"
                await msg.update()
                return "", "error"
        parts.append(item)
        await msg.stream_token(item)
    await msg.update()
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=2)
    except Exception:
        pass
    return "".join(parts), finish_reason


async def run_agent(goal: str, memory: list, settings: dict, step,
                    proj_instructions: str = ""):
    deep = settings.get("deep_think", False) if settings else False
    level = settings.get("reasoning_level", "High") if settings else "High"
    advanced = (settings.get("search_mode") == "Advanced Search") if settings else False
    model = _active_model()
    top_k = 10 if advanced else 6
    max_steps = (12 if advanced else 6) + (2 if level == "Max" else 0)
    max_tokens = 4096

    sys_prompt = SYSTEM_PROMPT
    if proj_instructions:
        sys_prompt += (f"\n\n# PROJECT SPECIFIC INSTRUCTIONS\n"
                       f"You are currently operating inside a project. "
                       f"Adhere strictly to these instructions:\n{proj_instructions}\n")
    if deep:
        sys_prompt += ("\n\nThink step by step before each tool call. "
                       "Verify a key aggregate with a second method when it matters.")

    messages = [{"role": "system", "content": sys_prompt},
                *memory, {"role": "user", "content": goal}]
    final_answer = None
    used_tools = False

    turn_context: dict = {
        "schema_queries": [],
        "sqls_run": [],
        "last_select_sql": None,
        "select_rows": 0,
    }

    for _ in range(max_steps):
        send = messages
        # Issue #12: Log headroom compression failures
        if HEADROOM_AVAILABLE:
            try:
                send = compress(messages, model=model)
            except Exception as e:
                _observe("headroom_compress_fail", error=str(e))
                send = messages

        resp = await asyncio.to_thread(
            llm_client.chat.completions.create,
            model=model, messages=send, tools=TOOLS,
            tool_choice="auto", temperature=0.1, max_tokens=max_tokens)
        msg = resp.choices[0].message

        am = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            am["tool_calls"] = [tc.model_dump() for tc in msg.tool_calls]
        messages.append(am)

        if msg.content:
            async with cl.Step(name="Thought 💭") as thought_step:
                thought_step.output = msg.content
                await thought_step.update()

        if not msg.tool_calls:
            if not msg.content:
                messages.append({"role": "user",
                                 "content": "Please respond with your answer or call a tool."})
                continue
            final_answer = msg.content
            break

        used_tools = True
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            name = tc.function.name

            if name == "search_schema":
                q = args.get("question", goal)
                async with cl.Step(name="🔎 search_schema") as tool_step:
                    tool_step.output = f"**Query:** {q}"
                    await tool_step.update()
                    result = await search_schema(q, top_k=top_k)
                    tool_step.output += f"\n\n**Results:**\n{result}"
                    await tool_step.update()
                turn_context["schema_queries"].append(q[:200])

            elif name == "run_sql":
                sql = args.get("sql", "")
                async with cl.Step(name="run_sql 🐘") as tool_step:
                    tool_step.output = f"```sql\n{sql}\n```"
                    await tool_step.update()
                    if sql.strip():
                        result = await run_sql(sql, tool_step)
                        turn_context["sqls_run"].append(sql[:300])
                        meta = cl.user_session.get("last_query_meta")
                        if meta and meta.get("stmt") == "SELECT":
                            turn_context["last_select_sql"] = sql
                            turn_context["select_rows"] = meta.get("total_rows", 0)
                    else:
                        result = "No SQL provided."
                    tool_step.output += f"\n\n**Execution Result:**\n{result}"
                    await tool_step.update()

            elif name == "visualize":
                state = cl.user_session.get("last_result")
                if not state or not state.get("rows"):
                    result = "No query result to visualize yet. Run a SELECT first."
                else:
                    try:
                        path, summary = await asyncio.to_thread(
                            _render_chart, state["rows"], args)
                        # Issue #4: Send chart then delete temp file immediately
                        await cl.Message(
                            content=f"📊{_HELPER_SENTINEL} Chart:",
                            elements=[cl.Image(path=path, name="chart",
                                               display="inline")]).send()
                        try:
                            os.unlink(path)
                        except Exception:
                            pass
                        result = (f"Chart rendered ({args.get('chart_type')}). "
                                  f"Aggregated data:\n{summary}")
                    except Exception as e:
                        result = (f"Visualization failed: {e}. "
                                  f"Adjust columns/agg and retry.")

                async with cl.Step(name="visualize 📊") as tool_step:
                    tool_step.output = f"**Args:** {json.dumps(args)}\n\n**Result:**\n{result}"
                    await tool_step.update()

            else:
                result = f"Unknown tool: {name}"

            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    if used_tools or final_answer is None:
        messages.append({"role": "user", "content":
            "Stop calling tools. Using ONLY the data already gathered above, write the final answer "
            "now with exact numbers in a table. Do not say you could not find the answer when data "
            "is present. If you discovered a data issue, suggest /learn-finding to persist it."})

        answer_msg = cl.Message(content="")
        await answer_msg.send()

        final_text = ""
        current_messages = messages

        # Issue #11: Cap total continuation tokens
        total_continuation_chars = 0
        for _ in range(3):
            try:
                text, finish_reason = await stream_llm(
                    current_messages, answer_msg, model=model,
                    temperature=0.1, max_tokens=max_tokens)
                final_text += text
                total_continuation_chars += len(text)

                # Rough estimate: ~4 chars per token
                if total_continuation_chars // 4 >= MAX_CONTINUATION_TOKENS:
                    final_text += "\n\n_[Response truncated to limit cost]_"
                    break

                if finish_reason == "length":
                    current_messages = current_messages + [
                        {"role": "assistant", "content": text},
                        {"role": "user", "content": "Continue generating the response exactly where you left off. Do not repeat any previous text."}
                    ]
                else:
                    break
            except Exception as e:
                final_text += f"\n\n[Could not synthesize final answer: {e}]"
                answer_msg.content = final_text
                await answer_msg.update()
                break

        answer_msg.content = final_text
        answer_msg.actions = _retry_actions(goal)
        await answer_msg.update()
        return (final_text or "No answer produced."), True, turn_context

    return (final_answer or "No answer produced."), False, turn_context


# --------------------------------------------------------------------------- #
#  Action Callbacks — All Static Names (Issue #1)
# --------------------------------------------------------------------------- #
@cl.action_callback(RETRY_ACTION)
async def on_retry(action: cl.Action):
    goal = (action.payload or {}).get("goal")
    if not goal:
        return
    _observe("action_retry", query=goal[:200])
    await _answer(goal)


# --------------------------------------------------------------------------- #
#  Projects UI — Native Modal Popup (Claude Desktop Style)
# --------------------------------------------------------------------------- #
from chainlit.input_widget import TextInput, Switch, Select

def _format_project_date(iso_str: str) -> str:
    # NOTE: %-d is not portable (fails on Windows), so format the day manually.
    try:
        dt = datetime.fromisoformat(iso_str.replace('Z', '+00:00'))
        return f"{dt.strftime('%b')} {dt.day}"
    except Exception:
        return "Recently"


def _esc(s) -> str:
    """Minimal HTML escaping for values interpolated into the dashboard HTML."""
    s = "" if s is None else str(s)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _md_html(html: str) -> str:
    """Prepare raw HTML for Chainlit markdown rendering.

    Markdown treats any line indented >= 4 spaces as a code block, which makes
    Chainlit render our dashboard HTML as escaped text instead of markup. Strip
    leading whitespace from every line so the HTML renders as HTML.
    """
    return "\n".join(line.lstrip() for line in html.splitlines())


def _relative_time(value) -> str:
    """Human 'x minutes/hours/days ago' from an ISO string, epoch, or datetime."""
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        elif isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
        else:
            dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        secs = (datetime.now(timezone.utc) - dt).total_seconds()
        if secs < 0:
            return "just now"
        if secs < 60:
            return "just now"
        if secs < 3600:
            m = int(secs // 60)
            return f"{m} minute{'s' if m != 1 else ''} ago"
        if secs < 86400:
            h = int(secs // 3600)
            return f"{h} hour{'s' if h != 1 else ''} ago"
        days = int(secs // 86400)
        if days == 1:
            return "yesterday"
        if days < 7:
            return f"{days} days ago"
        if days < 30:
            w = days // 7
            return f"{w} week{'s' if w != 1 else ''} ago"
        if days < 365:
            mo = days // 30
            return f"{mo} month{'s' if mo != 1 else ''} ago"
        y = days // 365
        return f"{y} year{'s' if y != 1 else ''} ago"
    except Exception:
        return "recently"


_FILE_BADGE_COLORS = {
    "SQL": ("#1d4ed8", "#dbeafe"), "MD": ("#374151", "#f3f4f6"),
    "CSV": ("#047857", "#d1fae5"), "JSON": ("#b45309", "#fef3c7"),
    "PDF": ("#b91c1c", "#fee2e2"), "TXT": ("#374151", "#f3f4f6"),
    "PY": ("#1d4ed8", "#dbeafe"), "YAML": ("#7c3aed", "#ede9fe"),
    "YML": ("#7c3aed", "#ede9fe"),
}
_TEXT_EXTS = {"sql", "md", "txt", "csv", "json", "py", "yaml", "yml", "log"}


async def _recent_project_tasks(project_id: str, limit: int = 7) -> list:
    """Best-effort fetch of recent conversation threads for the active project.

    Returns a list of (title, timestamp) tuples. Only threads whose stored
    chat profile matches the current project are included, so global threads
    are never mislabeled as belonging to this project. Returns [] if no data
    layer is configured, the query is slow, or anything goes wrong — the
    project workspace must always render regardless of thread history.
    """
    current_profile = cl.user_session.get("chat_profile")
    app_user = cl.user_session.get("user")

    async def _fetch() -> list:
        import chainlit.data as _cl_data
        data_layer = None
        if hasattr(_cl_data, "get_data_layer"):
            data_layer = _cl_data.get_data_layer()
        if data_layer is None:
            data_layer = getattr(_cl_data, "_data_layer", None)
        if data_layer is None or not app_user:
            return []

        from chainlit.types import Pagination, ThreadFilter
        persisted = await data_layer.get_user(app_user.identifier)
        if not persisted:
            return []
        resp = await data_layer.list_threads(
            Pagination(first=30), ThreadFilter(userId=persisted.id))

        out = []
        for th in (getattr(resp, "data", None) or []):
            md = th.get("metadata") or {}
            prof = md.get("chat_profile") if isinstance(md, dict) else None
            # Strict match: only include threads tagged with this project's profile.
            if not current_profile or prof != current_profile:
                continue
            title = th.get("name") or "Untitled conversation"
            ts = th.get("createdAt") or th.get("created_at")
            out.append((title, ts))
            if len(out) >= limit:
                break
        return out

    try:
        # Hard time-box: a slow/hanging data layer must never block the render.
        return await asyncio.wait_for(_fetch(), timeout=3.0)
    except asyncio.TimeoutError:
        _observe("project_tasks_timeout", project=project_id)
        return []
    except Exception as e:
        _observe("project_tasks_fetch_fail", error=str(e))
        return []


async def show_projects_dashboard():
    projects = list_projects()
    # Sort by created_at descending (mocking "Last updated")
    projects.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    # We use raw HTML inside Markdown to render the grid layout
    html = """
<div style="font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color: #333; width: 100%; background:#ffffff; padding:24px; border-radius:12px; border:1px solid #e5e7eb;">
  <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px;">
    <h2 style="margin: 0; font-size: 1.5rem; font-weight: 600; color:#111827;">Projects</h2>
  </div>

  <div style="display: flex; gap: 10px; margin-bottom: 24px;">
    <div style="flex: 1; border: 1px solid #d1d5db; border-radius: 6px; padding: 8px 12px; color: #9ca3af; font-size: 0.9rem; background: #fff;">
      🔍 Search projects...
    </div>
    <div style="border: 1px solid #d1d5db; border-radius: 6px; padding: 8px 12px; font-size: 0.9rem; color: #4b5563; background: #fff; cursor: pointer;">
      Sort by Last updated ▾
    </div>
  </div>

  <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 16px;">
    """

    if not projects:
        html += """
    <div style="grid-column: 1 / -1; text-align: center; padding: 40px; color: #888; border: 1px dashed #d1d5db; border-radius: 8px; background: #fff;">
      No projects found. Click "➕ New project" below to create one.
    </div>
    """
    else:
        for p in projects:
            proj_name = p.get("name", "Untitled")
            updated = _format_project_date(p.get("created_at", ""))
            instr = get_project_instructions(p["id"])
            desc = instr.split('\n')[0].replace('#', '').strip()
            if not desc or len(desc) < 5:
                desc = "No description provided. Use /set-instructions to add context."
            if len(desc) > 60:
                desc = desc[:57] + "..."

            html += f"""
    <div style="border: 1px solid #e5e7eb; border-radius: 8px; padding: 16px; background-color: #ffffff; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
      <h3 style="margin: 0 0 8px 0; font-size: 1.1rem; color: #111827; font-weight: 600;">{proj_name}</h3>
      <p style="margin: 0 0 12px 0; font-size: 0.8rem; color: #6b7280;">Updated {updated}</p>
      <p style="margin: 0; font-size: 0.9rem; color: #4b5563; line-height: 1.4; height: 40px; overflow: hidden; text-overflow: ellipsis;">{desc}</p>
    </div>
    """

    html += """
  </div>
</div>
    """

    actions = [
        cl.Action(name="create_project", payload={"value": "create"},
                  label="➕ New project", tooltip="Create a new project")
    ]
    if projects:
        # One "Open" button per project to launch its detail workspace
        for p in projects:
            actions.append(
                cl.Action(name="select_project", payload={"project_id": p["id"]},
                          label=f"Open {p['name']}"))
        actions.append(cl.Action(name="delete_project", payload={"value": "delete"},
                                 label="🗑️ Delete"))

    # NOTE: use cl.Message (not AskActionMessage) so the @cl.action_callback
    # handlers fire on click. AskActionMessage only returns the choice to its
    # caller and does not dispatch to action callbacks.
    await cl.Message(
        content=_md_html(html),
        actions=actions,
    ).send()


async def render_project_detail(project_id: str):
    """Renders the detailed Project Workspace view (Claude-style layout)."""
    _observe("project_detail_start", project=project_id)
    project = next((p for p in list_projects() if p["id"] == project_id), None)
    if not project:
        await cl.Message(content="❌ Project not found.").send()
        return

    cl.user_session.set("active_project", project_id)
    cl.user_session.set("memory", [])  # Clear memory for the new project workspace

    proj_name = project["name"]
    instructions = get_project_instructions(project_id)

    # ---- Model pill (real active model + reasoning level) ---- #
    model_name = _active_model()
    level = (cl.user_session.get("chat_settings") or {}).get("reasoning_level", "Max")

    # ---- Files & capacity (real data from the project KB dir) ---- #
    proj_kb_dir = PROJECTS_DIR / project_id / "knowledge"
    total_size_bytes = 0
    file_cards = []
    if proj_kb_dir.exists():
        for f in sorted(proj_kb_dir.glob("*")):
            if not f.is_file():
                continue
            size = f.stat().st_size
            total_size_bytes += size
            ext = f.suffix.lstrip(".").lower()
            badge = (ext.upper() or "FILE")
            fg, bg = _FILE_BADGE_COLORS.get(badge, ("#374151", "#f3f4f6"))
            if ext in _TEXT_EXTS:
                try:
                    with open(f, "r", encoding="utf-8", errors="ignore") as fh:
                        meta = f"{sum(1 for _ in fh)} lines"
                except Exception:
                    meta = (f"{size // 1024} KB" if size < 1024 * 1024
                            else f"{size / (1024 * 1024):.1f} MB")
            else:
                meta = (f"{size // 1024} KB" if size < 1024 * 1024
                        else f"{size / (1024 * 1024):.1f} MB")
            file_cards.append(f"""
        <div style="border:1px solid #e5e7eb; border-radius:10px; padding:12px 14px; background:#fff; display:flex; flex-direction:column; gap:8px; min-height:72px;">
          <div style="font-size:0.82rem; font-weight:500; color:#111827; word-break:break-word; line-height:1.25;">{_esc(f.name)}</div>
          <div style="font-size:0.72rem; color:#9ca3af;">{_esc(meta)}</div>
          <div><span style="font-size:0.62rem; font-weight:600; color:{fg}; background:{bg}; padding:2px 7px; border-radius:4px; letter-spacing:0.03em;">{_esc(badge)}</span></div>
        </div>""")

    if file_cards:
        files_inner = ('<div style="display:grid; grid-template-columns:repeat(2, 1fr); '
                       'gap:10px; margin-top:14px;">' + "".join(file_cards) + "</div>")
    else:
        files_inner = ('<p style="font-size:0.8rem; color:#9ca3af; margin-top:14px;">'
                       'No files yet. Click “📤 Upload files” below to add some.</p>')

    max_bytes = 50 * 1024 * 1024
    used_mb = total_size_bytes / (1024 * 1024)
    percent = min(int((total_size_bytes / max_bytes) * 100), 100) if max_bytes else 0

    # ---- Memory (optional memory.md, else placeholder) ---- #
    mem_path = PROJECTS_DIR / project_id / "memory.md"
    memory_text, mem_updated = "", ""
    if mem_path.exists():
        try:
            memory_text = mem_path.read_text(encoding="utf-8", errors="ignore").strip()
            mem_updated = _relative_time(mem_path.stat().st_mtime)
        except Exception:
            memory_text = ""
    if memory_text:
        snippet = memory_text.replace("\n", " ").strip()
        snippet = snippet[:160] + ("…" if len(snippet) > 160 else "")
        memory_body = f'<div style="font-size:0.85rem; color:#4b5563; line-height:1.45;">{_esc(snippet)}</div>'
        if mem_updated:
            memory_body += (f'<div style="font-size:0.72rem; color:#9ca3af; margin-top:8px;">'
                            f'Last updated {_esc(mem_updated)}</div>')
    else:
        memory_body = ('<div style="font-size:0.85rem; color:#9ca3af; line-height:1.45;">'
                       'No memory yet. As you work in this project, key context will live here. '
                       'Add a <code>memory.md</code> in the project folder to seed it.</div>')

    # ---- Instructions ---- #
    if instructions.strip():
        instr_snip = instructions.strip().replace("\n", " ")
        instr_snip = instr_snip[:200] + ("…" if len(instr_snip) > 200 else "")
        instr_body = f'<div style="font-size:0.85rem; color:#4b5563; line-height:1.45;">{_esc(instr_snip)}</div>'
    else:
        instr_body = ('<div style="font-size:0.85rem; color:#9ca3af; line-height:1.45;">'
                      'No instructions set. Click “✏️ Edit instructions” below to add context.</div>')

    # ---- Tasks (real recent threads for this project, best-effort) ---- #
    tasks = await _recent_project_tasks(project_id)
    if tasks:
        rows = []
        for title, ts in tasks:
            rows.append(f"""
      <div style="border-top:1px solid #f0f0f0; padding:14px 2px;">
        <div style="font-size:0.95rem; color:#111827;">{_esc(title)}</div>
        <div style="font-size:0.8rem; color:#9ca3af; margin-top:3px;">Last message {_esc(_relative_time(ts))}</div>
      </div>""")
        tasks_html = "".join(rows)
    else:
        tasks_html = ('<div style="border-top:1px solid #f0f0f0; padding:24px 2px; '
                      'font-size:0.85rem; color:#9ca3af;">No conversations in this project yet. '
                      'Ask a question below to start your first task.</div>')

    # ---- Assemble ---- #
    html = f"""
<div style="font-family:'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; color:#1f2937; width:100%; background:#ffffff; padding:24px; border-radius:12px; border:1px solid #e5e7eb;">
  <div style="font-size:0.85rem; color:#6b7280; margin-bottom:18px;">← All projects</div>

  <div style="display:flex; gap:32px; align-items:flex-start;">

    <!-- LEFT COLUMN -->
    <div style="flex:1.7; min-width:0;">
      <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:20px;">
        <h1 style="margin:0; font-size:1.7rem; font-weight:600; color:#111827;">{_esc(proj_name)}</h1>
        <div style="color:#9ca3af; font-size:1.1rem; display:flex; gap:14px;"><span>⋮</span><span>📌</span></div>
      </div>

      <!-- Chat input mockup -->
      <div style="border:1px solid #e5e7eb; border-radius:16px; padding:16px 18px; box-shadow:0 1px 3px rgba(0,0,0,0.04); background:#fff;">
        <div style="color:#9ca3af; font-size:1rem;">How can I help you today?</div>
        <div style="display:flex; align-items:center; justify-content:space-between; margin-top:34px;">
          <div style="width:30px; height:30px; border-radius:50%; border:1px solid #e5e7eb; display:flex; align-items:center; justify-content:center; color:#6b7280; font-size:1.1rem;">+</div>
          <div style="display:flex; align-items:center; gap:14px; color:#6b7280; font-size:0.85rem;">
            <span>{_esc(model_name)} <span style="color:#9ca3af;">{_esc(level)} ▾</span></span>
            <span>🎤</span><span>🔊</span>
          </div>
        </div>
      </div>

      <div style="text-align:center; color:#6b7280; font-size:0.9rem; margin:22px 0 6px 0;">⧉ Start a new task</div>

      <!-- Recent tasks -->
      <div style="margin-top:10px;">
        {tasks_html}
      </div>
    </div>

    <!-- RIGHT COLUMN -->
    <div style="flex:1; min-width:0; display:flex; flex-direction:column; gap:0; border:1px solid #ececec; border-radius:14px; overflow:hidden;">

      <!-- Memory -->
      <div style="padding:18px 18px 16px 18px; border-bottom:1px solid #f0f0f0;">
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:10px;">
          <span style="font-size:1.05rem; font-weight:600; color:#111827;">Memory</span>
          <span style="display:flex; align-items:center; gap:10px;">
            <span style="font-size:0.72rem; color:#6b7280; border:1px solid #e5e7eb; border-radius:6px; padding:2px 8px;">🔒 Only you</span>
            <span style="color:#9ca3af;">✏️</span>
          </span>
        </div>
        {memory_body}
      </div>

      <!-- Instructions -->
      <div style="padding:18px; border-bottom:1px solid #f0f0f0;">
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:10px;">
          <span style="font-size:1.05rem; font-weight:600; color:#111827;">Instructions</span>
          <span style="color:#9ca3af;">✏️</span>
        </div>
        {instr_body}
      </div>

      <!-- Files -->
      <div style="padding:18px;">
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px;">
          <span style="font-size:1.05rem; font-weight:600; color:#111827;">Files</span>
          <span style="color:#9ca3af; font-size:1.1rem;">+</span>
        </div>
        <div style="display:flex; justify-content:space-between; font-size:0.72rem; color:#6b7280; margin-bottom:5px;">
          <span>{percent}% of project capacity used</span>
          <span>{used_mb:.1f} MB / 50.0 MB</span>
        </div>
        <div style="width:100%; background:#eceef1; border-radius:4px; height:6px;">
          <div style="width:{percent}%; background:#2563eb; height:6px; border-radius:4px;"></div>
        </div>
        {files_inner}
      </div>

    </div>
  </div>
</div>
    """

    actions = [
        cl.Action(name="upload_files", payload={"project_id": project_id},
                  label="📤 Upload files", tooltip="Upload files to project KB"),
        cl.Action(name="edit_instructions", payload={"project_id": project_id},
                  label="✏️ Edit instructions"),
        cl.Action(name="back_to_dashboard", payload={"value": "back"},
                  label="← All projects")
    ]

    _observe("project_detail_pre_send", project=project_id, tasks=len(tasks))
    # NOTE: use cl.Message (not AskActionMessage) so the @cl.action_callback
    # handlers fire on click. AskActionMessage only returns the choice to its
    # caller and does not dispatch to action callbacks.
    await cl.Message(
        content=_md_html(html),
        actions=actions,
    ).send()


# --------------------------------------------------------------------------- #
#  Action Callbacks for Project Workspace
# --------------------------------------------------------------------------- #
@cl.action_callback("back_to_dashboard")
async def on_back_to_dashboard(action):
    await show_projects_dashboard()


@cl.action_callback("select_project")
async def on_select_project(action):
    project_id = action.payload.get("project_id")
    if project_id:
        await render_project_detail(project_id)


@cl.action_callback("upload_files")
async def on_upload_files(action):
    project_id = action.payload.get("project_id")
    if project_id:
        cl.user_session.set("active_project", project_id)
    await cl.Message(
        content="📤 Attach file(s) to your next message and include the word "
                "**learn** (or **save**) — they'll be ingested into this project's "
                "isolated knowledge base.").send()


@cl.action_callback("create_project")
async def on_create_project(action):
    current_settings = cl.user_session.get("chat_settings") or {}
    
    # Build a modal form that includes project creation fields 
    # AND preserves the existing chat settings so they aren't lost
    widgets = [
        TextInput(id="project_name", label="Name your project", placeholder="Hero Slides Analysis", initial=""),
        TextInput(id="project_description", label="Describe your project, goals, subject, etc...", placeholder="e.g. Tracking hero slide click performance", multi_line=True, initial=""),
        Switch(id="deep_think", label="Deep Think", initial=current_settings.get("deep_think", False)),
        Select(id="reasoning_level", label="Reasoning Level", values=["High", "Max"], initial=current_settings.get("reasoning_level", "High")),
        Select(id="search_mode", label="Search Mode", values=["Search", "Advanced Search"], initial=current_settings.get("search_mode", "Search"))
    ]
    
    # Display the modal (this blocks until the user saves or cancels)
    form_result = await cl.ChatSettings(widgets).send()
    
    # Save the chat settings regardless of whether they created a project
    if form_result:
        cl.user_session.set("chat_settings", form_result)
    
    if not form_result or not form_result.get("project_name"):
        if form_result is None:
            await cl.Message(content="Project creation cancelled.").send()
        return
        
    name = form_result["project_name"].strip()
    description = form_result.get("project_description", "").strip()
    
    project = create_project(name)
    if description:
        save_project_instructions(project["id"], description)
        
    cl.user_session.set("active_project", project["id"])
    cl.user_session.set("memory", [])  # Isolate memory for the new project
    
    await cl.Message(content=f"✅ Project **{name}** created and activated!\n\n💡 *To switch between projects easily in the future, click the **New Chat** button in the sidebar and select this project.*").send()


@cl.action_callback("exit_project")
async def on_exit_project(action):
    cl.user_session.set("active_project", None)
    cl.user_session.set("memory", [])
    await cl.Message(content="🚪 Exited project. Returned to global mode.").send()
    await show_projects_dashboard()


@cl.action_callback("edit_instructions")
async def on_edit_instructions(action):
    projects = list_projects()
    if not projects:
        await cl.Message(content="No projects available to edit.").send()
        return
    actions = [
        cl.Action(name="edit_project_select",
                  payload={"project_id": p["id"]}, label=p["name"])
        for p in projects
    ]
    await cl.Message(
        content="Select a project to edit instructions for:",
        actions=actions).send()


@cl.action_callback("edit_project_select")
async def on_edit_project_select(action):
    project_id = action.payload.get("project_id")
    if not project_id:
        return
        
    current_instr = get_project_instructions(project_id)
    current_settings = cl.user_session.get("chat_settings") or {}
    
    widgets = [
        TextInput(id="instructions", label=f"Edit Instructions for {project_id}", multi_line=True, initial=current_instr),
        Switch(id="deep_think", label="Deep Think", initial=current_settings.get("deep_think", False)),
        Select(id="reasoning_level", label="Reasoning Level", values=["High", "Max"], initial=current_settings.get("reasoning_level", "High")),
        Select(id="search_mode", label="Search Mode", values=["Search", "Advanced Search"], initial=current_settings.get("search_mode", "Search"))
    ]
    
    form_result = await cl.ChatSettings(widgets).send()
    
    if form_result:
        cl.user_session.set("chat_settings", form_result)
        new_instr = form_result.get("instructions", "").strip()
        if new_instr != current_instr:
            save_project_instructions(project_id, new_instr)
            await cl.Message(content="✅ Instructions updated successfully.").send()
        else:
            await cl.Message(content="No changes made to instructions.").send()
    else:
        await cl.Message(content="Edit cancelled.").send()


@cl.action_callback("delete_project")
async def on_delete_project(action):
    projects = list_projects()
    if not projects:
        await cl.Message(content="No projects available to delete.").send()
        return
    actions = [
        cl.Action(name="delete_project_select",
                  payload={"project_id": p["id"]},
                  label=f"Delete {p['name']}")
        for p in projects
    ]
    await cl.Message(
        content="⚠️ Select a project to permanently delete (this cannot be undone):",
        actions=actions).send()


@cl.action_callback("delete_project_select")
async def on_delete_project_select(action):
    project_id = action.payload.get("project_id")
    if project_id:
        deleted = delete_project(project_id)
        if deleted:
            if cl.user_session.get("active_project") == project_id:
                cl.user_session.set("active_project", None)
                cl.user_session.set("memory", [])
            await cl.Message(content=f"🗑️ Project `{project_id}` deleted successfully.").send()
        else:
            await cl.Message(content=f"❌ Failed to delete project `{project_id}`.").send()
        await show_projects_dashboard()

# --------------------------------------------------------------------------- #
#  Chainlit Handlers (Update on_message section)
# --------------------------------------------------------------------------- #
@cl.on_message
async def on_message(message: cl.Message):
    global _skills
    if not _skills:
        try:
            _skills = _load_skills()
        except Exception as e:
            _observe("skills_load_error", error=str(e))
            _skills = {}

    goal = message.content.strip()

    # ----------------- Project Management Commands ----------------- #
    if goal.lower() == "/projects":
        await show_projects_dashboard()
        return

    if goal.lower().startswith("/project "):
        proj_name = goal[len("/project "):].strip()
        projects = list_projects()
        # Try to find the project first
        matched = next((p for p in projects
                        if p["id"] == _slugify(proj_name)
                        or p["name"].lower() == proj_name.lower()), None)
        if matched:
            cl.user_session.set("active_project", matched["id"])
            cl.user_session.set("memory", [])
            await cl.Message(
                content=f"🗂️ Switched to project: **{matched['name']}**").send()
        else:
            # If not found, create it automatically (frictionless UX)
            project = create_project(proj_name)
            cl.user_session.set("active_project", project["id"])
            cl.user_session.set("memory", [])
            await cl.Message(
                content=f"✅ Project **{proj_name}** created and activated!").send()
        return

    # ... (keep the rest of your /set-instructions and slash commands here)
async def handle_delete_selection(project_id: str):
    deleted = delete_project(project_id)
    if deleted:
        if cl.user_session.get("active_project") == project_id:
            cl.user_session.set("active_project", None)
            cl.user_session.set("memory", [])
        await cl.Message(content=f"🗑️ Project `{project_id}` deleted successfully.").send()
    else:
        await cl.Message(content=f"❌ Failed to delete project `{project_id}`.").send()
    await show_projects_dashboard()



# --------------------------------------------------------------------------- #
#  Auth + Persistence
# --------------------------------------------------------------------------- #
DATABASE_URL = os.getenv("DATABASE_URL")
DB_SSL = os.getenv("DB_SSL", "false").lower() == "true"
APP_USERNAME = os.getenv("APP_USERNAME", "")
APP_PASSWORD = os.getenv("APP_PASSWORD", "")
GCS_BUCKET = os.getenv("GCS_BUCKET", "")
GCS_PROJECT_ID = os.getenv("GCS_PROJECT_ID", "")
GCS_CLIENT_EMAIL = os.getenv("GCS_CLIENT_EMAIL", "")

llm_client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))

if APP_USERNAME and APP_PASSWORD:
    print(f"[AUTH] Password auth active for user: '{APP_USERNAME}'", file=_sys.stderr)

    @cl.password_auth_callback
    def auth_callback(username, password):
        _observe("auth_attempt", username=username,
                 match=(username == APP_USERNAME and password == APP_PASSWORD))
        # Issue #24: Constant-time password comparison
        if (username == APP_USERNAME and
                hmac.compare_digest(password, APP_PASSWORD)):
            return cl.User(identifier=username, metadata={"role": "owner"})
        return None
else:
    _reason = "APP_USERNAME empty" if not APP_USERNAME else "APP_PASSWORD empty"
    print(f"[AUTH] WARNING: password auth NOT active ({_reason}). "
          f"Set both in .env to enable login.", file=_sys.stderr)


if DATABASE_URL:
    @cl.data_layer
    def get_data_layer():
        from chainlit.data.sql_alchemy import SQLAlchemyDataLayer
        storage = None
        if GCS_BUCKET:
            try:
                from chainlit.data.storage_clients.gcs import GCSStorageClient
                # Issue #17: Lazy-load GCS private key
                storage = GCSStorageClient(
                    bucket_name=GCS_BUCKET,
                    project_id=GCS_PROJECT_ID or PROJECT_ID,
                    client_email=GCS_CLIENT_EMAIL or None,
                    private_key=_get_gcs_private_key() or None,
                )
                print(f"[DB] GCS storage configured: gs://{GCS_BUCKET}", file=_sys.stderr)
            except Exception as e:
                print(f"[DB] WARNING: GCS storage client failed: {e}", file=_sys.stderr)
                storage = None
        else:
            print("[DB] No GCS_BUCKET set. File attachments will not be "
                  "persisted (chat messages will be).", file=_sys.stderr)
        return SQLAlchemyDataLayer(
            conninfo=DATABASE_URL, storage_provider=storage, ssl_require=DB_SSL)

    _db_host = (DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else '(local)')
    print(f"[DB] Persistence configured: {_db_host}", file=_sys.stderr)


# --------------------------------------------------------------------------- #
#  Chainlit Handlers
# --------------------------------------------------------------------------- #
@cl.on_chat_resume
async def on_chat_resume(thread):
    settings = await cl.ChatSettings([
        Select(id="model", label="Agent Model", values=GLM_MODELS, initial=AGENT_MODEL),
        Switch(id="deep_think", label="Deep Think", initial=False),
        Select(id="reasoning_level", label="Reasoning Level",
               values=["High", "Max"], initial="High"),
        Select(id="search_mode", label="Search Mode",
               values=["Search", "Advanced Search"], initial="Search"),
    ]).send()
    cl.user_session.set("chat_settings", settings)
    cl.user_session.set("model", settings.get("model", AGENT_MODEL))

    memory = []
    last_select_sql = None
    for s in thread.get("steps", []):
        stype = s.get("type")
        if stype == "user_message":
            memory.append({"role": "user", "content": s.get("output", "") or ""})
        elif stype == "assistant_message":
            out = s.get("output", "") or ""
            if _HELPER_SENTINEL in out:
                continue
            memory.append({"role": "assistant", "content": out})
            ctx_match = re.search(r'\[Turn context: ({.*?})\]\s*$', out)
            if ctx_match:
                try:
                    ctx = json.loads(ctx_match.group(1))
                    # Issue #7: Properly restore SQL hint from turn context
                    if ctx.get("last_select_sql") and ctx.get("select_rows", 0) > 0:
                        last_select_sql = ctx["last_select_sql"]
                except Exception:
                    pass

    cl.user_session.set("memory", memory[-MEMORY_TURNS:])
    if last_select_sql:
        cl.user_session.set("turn_sql", last_select_sql)
        cl.user_session.set("resumed_sql_hint", last_select_sql)
    else:
        cl.user_session.set("resumed_sql_hint", None)

    chunks, files, skipped = await ingest_wiki()
    if not skipped:
        _observe("wiki_reingest_resume", chunks=chunks, files=files)


@cl.on_chat_start
async def start_chat():
    # 1. Determine Project from Chat Profile
    chat_profile = cl.user_session.get("chat_profile") or "🌍 Global Mode"
    active_project = None

    if chat_profile.startswith("🗂️ "):
        proj_name = chat_profile[3:]
        projects = list_projects()
        matched = next((p for p in projects if p["name"] == proj_name), None)
        if matched:
            active_project = matched["id"]

    cl.user_session.set("active_project", active_project)
    cl.user_session.set("memory", [])
    cl.user_session.set("resumed_sql_hint", None)

    # 2. Setup Chat Settings (Moved Model selection here)
    settings = await cl.ChatSettings([
        Select(id="model", label="Agent Model", values=GLM_MODELS, initial=AGENT_MODEL),
        Switch(id="deep_think", label="Deep Think", initial=False),
        Select(id="reasoning_level", label="Reasoning Level",
               values=["High", "Max"], initial="High"),
        Select(id="search_mode", label="Search Mode",
               values=["Search", "Advanced Search"], initial="Search"),
    ]).send()
    cl.user_session.set("chat_settings", settings)
    cl.user_session.set("model", settings.get("model", AGENT_MODEL))

    chunks, files, skipped = await ingest_wiki()
    if skipped:
        _observe("wiki_unchanged")
    else:
        _observe("wiki_ingested", chunks=chunks, files=files)

    try:
        get_bq_client()
    except Exception as e:
        await cl.Message(
            content=f"❌ **Auth error**: run `gcloud auth application-default login`, "
                    f"then reload.\n{e}"
        ).send()

    # 3. Render the project workspace if one was selected from the sidebar.
    #    Placed last because AskActionMessage blocks until the user acts.
    if active_project:
        await render_project_detail(active_project)


@cl.on_settings_update
async def update_settings(settings):
    cl.user_session.set("chat_settings", settings)
    cl.user_session.set("model", settings.get("model", AGENT_MODEL))
    _observe("settings_update", deep=settings.get("deep_think"),
             level=settings.get("reasoning_level"),
             search=settings.get("search_mode"),
             model=settings.get("model"))


# --------------------------------------------------------------------------- #
#  Chat Profiles -> Projects Sidebar UI
# --------------------------------------------------------------------------- #
@cl.set_chat_profiles
async def chat_profiles(user=None):
    profiles = [
        cl.ChatProfile(
            name="🌍 Global Mode",
            markdown_description="Default AJ360 agent without project isolation.",
            default=True
        )
    ]
    # Dynamically add all existing projects to the "New Chat" sidebar
    for p in list_projects():
        profiles.append(
            cl.ChatProfile(
                name=f"🗂️ {p['name']}",
                markdown_description=f"**Project Context**\nIsolated KB & Custom Instructions."
            )
        )
    return profiles


# Issue #20: Configurable starters via STARTERS_FILE env var
@cl.set_starters
async def starters():
    if STARTERS_FILE:
        path = Path(STARTERS_FILE)
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return [
                    cl.Starter(label=s["label"], message=s["message"])
                    for s in data
                ]
            except Exception as e:
                _observe("starters_load_fail", file=str(path), error=str(e))
    # Default starters
    return [
        cl.Starter(
            label="🗂️ Manage Projects",
            message="/projects",
            icon="/public/projects.svg"),
        cl.Starter(
            label="Hero slides · last 7 days",
            message="Show the top hero slides by total clicks over the last 7 days, "
                    "broken down by device."),
        cl.Starter(
            label="Daily active guests",
            message="How many distinct guests opened the app each day over the last "
                    "7 days? Show a line chart."),
        cl.Starter(
            label="Search funnel by platform",
            message="Break down the search funnel (searches, results shown, result "
                    "clicks) by platform for the last 7 days."),
        cl.Starter(
            label="Top series by watch time",
            message="Top 10 series by total watch time over the last 14 days. "
                    "Aggregate on series_id and show the title."),
    ]


# --------------------------------------------------------------------------- #
#  Chainlit Handlers (Update on_message section)
# --------------------------------------------------------------------------- #
@cl.on_message
async def on_message(message: cl.Message):
    global _skills
    if not _skills:
        try:
            _skills = _load_skills()
        except Exception as e:
            _observe("skills_load_error", error=str(e))
            _skills = {}

    goal = message.content.strip()

    # ----------------- Project Management Commands ----------------- #
    if goal.lower() == "/projects":
        await show_projects_dashboard()
        return

    if goal.lower().startswith("/project "):
        proj_name = goal[len("/project "):].strip()
        projects = list_projects()
        # Try to find the project first
        matched = next((p for p in projects
                        if p["id"] == _slugify(proj_name)
                        or p["name"].lower() == proj_name.lower()), None)
        if matched:
            cl.user_session.set("active_project", matched["id"])
            cl.user_session.set("memory", [])
            await cl.Message(
                content=f"🗂️ Switched to project: **{matched['name']}**").send()
        else:
            # If not found, create it automatically (frictionless UX)
            project = create_project(proj_name)
            cl.user_session.set("active_project", project["id"])
            cl.user_session.set("memory", [])
            await cl.Message(
                content=f"✅ Project **{proj_name}** created and activated!\n\n💡 *To access this project from the sidebar in the future, start a 'New Chat' and select it from the dropdown.*").send()
        return

    if goal.lower().startswith("/set-instructions"):
        active = cl.user_session.get("active_project")
        if not active:
            await cl.Message(
                content="❌ No active project. Switch to a project first using "
                        "`/project <name>`.").send()
            return
        new_instr = goal[len("/set-instructions"):].strip()
        if new_instr:
            save_project_instructions(active, new_instr)
            await cl.Message(content="✅ Project instructions updated successfully.").send()
        else:
            await cl.Message(
                content="Usage: `/set-instructions <your markdown instructions>`").send()
        return

    # ... (keep the rest of your /skills and slash commands here)

    # ----------------- Built-in Slash Commands ----------------- #
    if goal.lower() == "/skills":

        if not _skills:
            _skills = _load_skills()
        if not _skills:
            await cl.Message(content="No skills found. Add .md files to `skills/`.").send()
            return
        lines = ["## Available Skills\n"]
        for name, skill in _skills.items():
            auto = " 🔄 auto" if skill.auto else ""
            lines.append(f"### `/{name}`{auto}\n{skill.description}\n")
            if skill.triggers:
                lines.append(f"**Triggers**: {', '.join(skill.triggers[:8])}")
            if skill.file_triggers:
                lines.append(f"**File triggers**: {', '.join(skill.file_triggers)}")
            if skill.references:
                lines.append(f"**References**: {', '.join(skill.references)}")
            lines.append("")
        await cl.Message(content="\n".join(lines)).send()
        return

    if goal.lower() == "/reload-skills":
        _skills = _load_skills()
        await cl.Message(
            content=f"✅ Reloaded {len(_skills)} skill(s): "
                    f"{', '.join(f'/{n}' for n in _skills)}").send()
        return

    if goal.lower() in ("/refresh-catalog", "/rebuild-catalog"):
        async with cl.Step(name="Rebuilding catalog 📚") as step:
            n, errors = await rebuild_catalog()
            step.output = f"Rebuilt: {n} tables."
            await step.update()
        if errors:
            err_lines = "\n".join(f"- {e}" for e in errors[:10])
            await cl.Message(
                content=f"✅ {n} tables indexed.\n⚠️ {len(errors)} skipped:\n{err_lines}").send()
        else:
            await cl.Message(content=f"✅ {n} tables indexed.").send()
        return

    if goal.lower().startswith("/learn-finding"):
        finding = goal[len("/learn-finding"):].strip()
        if not finding:
            await cl.Message(content="**Usage:** `/learn-finding <description>`").send()
            return
        try:
            resp = await asyncio.to_thread(
                llm_client.chat.completions.create, model=FLASH_MODEL,
                messages=[{"role": "system", "content": "Structure this as a wiki entry."},
                          {"role": "user", "content": finding}],
                temperature=0.1, max_tokens=500)
            structured = resp.choices[0].message.content or finding
        except Exception:
            structured = finding
        category = "data_issues"
        if any(w in finding.lower() for w in ("query", "sql", "pattern")):
            category = "query_patterns"
        elif any(w in finding.lower() for w in ("rule", "must", "never")):
            category = "aj360_rules"
        await asyncio.to_thread(_append_finding_to_wiki, structured, category)
        await ingest_wiki()
        await cl.Message(content=f"✅ Saved to `knowledge/{category}.md`").send()
        return

    if goal.lower().startswith("/lint-knowledge"):
        results = await asyncio.to_thread(_lint_wiki_sync)
        lines = ["## Wiki Health\n"]
        for f in results["files"]:
            lines.append(f"- `{f['path']}` {f['sections']}§ {f['age_days']}d old")
        if results["issues"]:
            lines.append("\n⚠️ Issues:\n" + "\n".join(f"- {i}" for i in results["issues"]))
        if results["suggestions"]:
            lines.append("\n💡 Suggestions:\n" + "\n".join(f"- {s}" for s in results["suggestions"]))
        if not results["issues"] and not results["suggestions"]:
            lines.append("✅ Healthy.")
        await cl.Message(content="\n".join(lines)).send()
        return

    # ----------------- Skill Matching ----------------- #
    skill_instructions = ""
    matched_skill = None
    matched_via_auto = False

    # 1. Explicit slash command: /skill-name [args]
    #    Use word-boundary check to avoid /hero matching /hero-slides
    if goal.startswith("/"):
        for name, skill in _skills.items():
            cmd = f"/{name}"
            if goal.lower() == cmd or goal.lower().startswith(cmd + " "):
                matched_skill = skill
                goal = goal[len(cmd):].strip()
                if not goal:
                    goal = f"Run the {name} skill."
                break

    # 2. Auto-trigger: word-boundary keyword match or uploaded-filename match
    if not matched_skill:
        for name, skill in _skills.items():
            if skill.auto and (skill.matches_text(goal)
                               or skill.matches_files(message.elements)):
                matched_skill = skill
                matched_via_auto = True
                break

    if matched_skill:
        skill_instructions = matched_skill.instructions
        # Issue #21: Load only references specified in skill frontmatter
        ref_dir = SKILLS_DIR / "references"
        if ref_dir.is_dir():
            refs = []
            ref_files = matched_skill.references if matched_skill.references else None
            for rp in sorted(ref_dir.glob("*.md")):
                if ref_files and rp.stem not in ref_files:
                    continue
                try:
                    refs.append(f"### reference: {rp.name}\n{rp.read_text(encoding='utf-8')}")
                except Exception as e:
                    refs.append(f"### reference: {rp.name} — read failed: {e}")
            if refs:
                skill_instructions += "\n\n# SKILL REFERENCES\n\n" + "\n\n".join(refs)
        _observe("skill_triggered", name=matched_skill.name, via_auto=matched_via_auto)

    # ----------------- "learn"/"save" with files → ingest to KB ----------------- #
    if message.elements and ("learn" in goal.lower() or "save" in goal.lower()):
        active_project = cl.user_session.get("active_project")
        if active_project:
            async with cl.Step(name="Learning files to Project KB 🗂️📚") as step:
                total = await ingest_to_project(active_project, message.elements, step)
                step.output = (f"✅ Saved {len(message.elements)} file(s) "
                               f"to project knowledge base.")
                await step.update()
        else:
            async with cl.Step(name="Learning files 📚") as step:
                await ingest_files(message.elements, step)
                step.output = (f"✅ Saved {len(message.elements)} file(s) "
                               f"to global knowledge base.")
                await step.update()
        await cl.Message(content="✅ Files added to knowledge base.").send()
        return

    # ----------------- Read uploaded files for THIS turn ----------------- #
    image_descriptions = ""
    doc_text = ""

    if message.elements:
        image_elements = [el for el in message.elements
                          if (el.mime or "").startswith("image")]
        doc_elements = [el for el in message.elements
                        if not (el.mime or "").startswith("image")]

        if image_elements:
            async with cl.Step(name=f"Analyzing {len(image_elements)} image(s) 🖼️") as step:
                image_descriptions = await _process_images(image_elements, step)

        if doc_elements:
            async with cl.Step(name=f"Reading {len(doc_elements)} document(s) 📄") as step:
                parts = []
                for el in doc_elements:
                    step.output = f"Reading {el.name}..."
                    await step.update()
                    try:
                        txt = await asyncio.to_thread(
                            extract_text_from_file, el.path, el.mime or "")
                        parts.append(f"**Document: {el.name}**\n{txt[:20000]}")
                    except Exception as e:
                        parts.append(f"**Document: {el.name}** — read failed: {e}")
                doc_text = "\n\n".join(parts)
                step.output = (f"Read {len(doc_elements)} document(s). "
                               f"Say \"learn\" to also save them to the KB.")
                await step.update()

    # ----------------- Guard: nothing to act on ----------------- #
    if not goal and not image_descriptions and not doc_text:
        await cl.Message(content="Please provide a question or upload a file.").send()
        return

    # ----------------- Build effective goal ----------------- #
    # Issue #14: Context ordering — skill_instructions (prepended in _answer)
    # is followed by ImageContext, then DocumentContext, then User goal.
    # This keeps image descriptions close to skill instructions that may
    # reference them.
    if not goal:
        goal = "Analyze the uploaded file(s) and report what you find."

    context_parts = []
    if image_descriptions:
        context_parts.append(f"---\nImageContext (vision model):\n{image_descriptions}")
    if doc_text:
        context_parts.append(f"---\nDocumentContext (extracted text):\n{doc_text}")

    if context_parts:
        goal = "\n\n".join(context_parts) + f"\n\n---\nUser goal:\n{goal}"

    await _answer(goal, skill_instructions)