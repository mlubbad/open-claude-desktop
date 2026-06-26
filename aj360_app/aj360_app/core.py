"""
AJ360 backend core — Chainlit-free.

Extracted from the original Chainlit app.py so the Reflex UI can reuse the
exact same on-disk data: ./projects (registry + per-project instructions/KB),
./knowledge (wiki), ./chroma_db (vector store). Both apps stay data-compatible.

Only pure logic lives here (filesystem + ChromaDB + small helpers). BigQuery and
LLM agent integration are added in a later milestone.
"""
from __future__ import annotations

import os
import re
import json
import time
import uuid
import hashlib
import threading
from datetime import datetime, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
#  Paths — resolve the repo root so we share data with the Chainlit app.
#  core.py lives at <repo>/aj360_app/aj360_app/core.py -> parents[2] == <repo>.
#  Override with AJ360_DATA_DIR if the layout ever changes.
# --------------------------------------------------------------------------- #
REPO_ROOT = Path(os.getenv("AJ360_DATA_DIR", str(Path(__file__).resolve().parents[2])))

# Load the shared .env (ZHIPU_API_KEY, GCP_PROJECT_ID, …) from the repo root.
try:
    from dotenv import load_dotenv
    load_dotenv(REPO_ROOT / ".env")
except Exception:
    pass

PROJECTS_DIR = Path(os.getenv("PROJECTS_DIR", str(REPO_ROOT / "projects")))
KNOWLEDGE_DIR = Path(os.getenv("KNOWLEDGE_DIR", str(REPO_ROOT / "knowledge")))
CHROMA_PATH = os.getenv("CHROMA_PATH", str(REPO_ROOT / "chroma_db"))

PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
_REGISTRY_FILE = PROJECTS_DIR / "_registry.json"

# Per-project storage cap shown in the UI (mock, matches the Chainlit app).
PROJECT_CAPACITY_BYTES = int(os.getenv("PROJECT_CAPACITY_MB", "50")) * 1024 * 1024

# Models (for the chat composer pill / settings).
AGENT_MODEL = os.getenv("AGENT_MODEL", os.getenv("PLANNER_MODEL", "glm-4-plus"))
_glm_default = f"{AGENT_MODEL},glm-4.5-air,glm-4-flash,glm-4-long"
GLM_MODELS: list[str] = []
for _m in os.getenv("GLM_MODELS", _glm_default).split(","):
    _m = _m.strip()
    if _m and _m not in GLM_MODELS:
        GLM_MODELS.append(_m)

_TEXT_EXTS = {"sql", "md", "txt", "csv", "json", "py", "yaml", "yml", "log"}

# --------------------------------------------------------------------------- #
#  Global app settings (Customize page)
# --------------------------------------------------------------------------- #
_SETTINGS_FILE = REPO_ROOT / "aj360_settings.json"
EFFORT_LEVELS = ["Low", "Medium", "High", "Max"]
# Claude-style "Extended thinking" levels — each maps to real backend behaviour
# (steps cap + planning/verification passes + temperature) in agent.EFFORT.
EFFORT_DESCRIPTIONS = {
    "Low": "Fast, direct answers",
    "Medium": "A little more checking",
    "High": "Plans before answering",
    "Max": "Plans, then self-verifies",
}
DEFAULT_SETTINGS = {"model": AGENT_MODEL, "effort": "High", "theme": "light"}


def get_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    try:
        if _SETTINGS_FILE.exists():
            data = json.loads(_SETTINGS_FILE.read_text(encoding="utf-8"))
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
        _SETTINGS_FILE.write_text(json.dumps(s, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
    except Exception:
        pass
    return s


# --------------------------------------------------------------------------- #
#  Lazy ChromaDB (only touched for file ingest / KB search, not for listing)
# --------------------------------------------------------------------------- #
_chroma = None


def _get_chroma():
    global _chroma
    if _chroma is None:
        import chromadb
        _chroma = chromadb.PersistentClient(path=CHROMA_PATH)
    return _chroma


def get_project_kb_collection(project_id: str):
    return _get_chroma().get_or_create_collection(f"kb_project_{project_id}")


def get_project_allowlist(project_id: str) -> list:
    """Optional per-project table allowlist (projects/<id>/allowlist.json)."""
    path = PROJECTS_DIR / project_id / "allowlist.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


# --------------------------------------------------------------------------- #
#  Projects registry (identical semantics to app.py)
# --------------------------------------------------------------------------- #
def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "untitled"


def _load_registry() -> list[dict]:
    if _REGISTRY_FILE.exists():
        try:
            return json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
    return []


def _save_registry(data: list[dict]):
    tmp = _REGISTRY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(_REGISTRY_FILE)


def list_projects() -> list[dict]:
    return _load_registry()


def get_project(project_id: str) -> dict | None:
    return next((p for p in _load_registry() if p["id"] == project_id), None)


def create_project(name: str) -> dict:
    projects = _load_registry()
    project_id = _slugify(name)
    if project_id in {p["id"] for p in projects}:
        project_id = f"{project_id}-{uuid.uuid4().hex[:4]}"

    (PROJECTS_DIR / project_id / "knowledge").mkdir(parents=True, exist_ok=True)
    instructions_path = PROJECTS_DIR / project_id / "instructions.md"
    if not instructions_path.exists():
        instructions_path.write_text(
            f"# Instructions for {name}\n\nAdd specific guidelines for this project here.\n",
            encoding="utf-8")

    meta = {"id": project_id, "name": name,
            "created_at": datetime.now(timezone.utc).isoformat()}
    projects.append(meta)
    _save_registry(projects)
    return meta


def delete_project(project_id: str) -> bool:
    projects = _load_registry()
    updated = [p for p in projects if p["id"] != project_id]
    if len(updated) == len(projects):
        return False
    _save_registry(updated)
    proj_dir = PROJECTS_DIR / project_id
    if proj_dir.exists():
        import shutil
        shutil.rmtree(proj_dir, ignore_errors=True)
    try:
        _get_chroma().delete_collection(f"kb_project_{project_id}")
    except Exception:
        pass
    return True


def get_project_instructions(project_id: str) -> str:
    path = PROJECTS_DIR / project_id / "instructions.md"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def save_project_instructions(project_id: str, content: str):
    path = PROJECTS_DIR / project_id / "instructions.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def get_project_memory(project_id: str) -> tuple[str, str]:
    """Returns (memory_text, last_updated_relative) from optional memory.md."""
    path = PROJECTS_DIR / project_id / "memory.md"
    if path.exists():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").strip()
            return text, relative_time(path.stat().st_mtime)
        except Exception:
            return "", ""
    return "", ""


def save_project_memory(project_id: str, content: str):
    path = PROJECTS_DIR / project_id / "memory.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# --------------------------------------------------------------------------- #
#  Per-project CONVERSATIONS (Claude-style threads)
#  Each conversation is projects/<id>/conversations/<cid>.json:
#    {id, title, created_at, updated_at, messages: [{role, content, kind}, ...]}
# --------------------------------------------------------------------------- #
CONV_MAX_MESSAGES = int(os.getenv("CONV_MAX_MESSAGES", "400"))

# Reserved space for non-project ("General") conversations — New chat / Cowork.
GENERAL_ID = "general"
GENERAL_NAME = "General"


def _conv_dir(project_id: str) -> Path:
    return PROJECTS_DIR / project_id / "conversations"


def _conv_path(project_id: str, conv_id: str) -> Path:
    return _conv_dir(project_id) / f"{conv_id}.json"


def _conv_title_from(text: str) -> str:
    t = " ".join((text or "").split())
    return (t[:48] + "…") if len(t) > 48 else (t or "New conversation")


def _write_conversation(project_id: str, conv: dict):
    d = _conv_dir(project_id)
    d.mkdir(parents=True, exist_ok=True)
    path = _conv_path(project_id, conv["id"])
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(conv, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # atomic


def create_conversation(project_id: str, first_message: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    conv = {
        "id": uuid.uuid4().hex[:12],
        "title": _conv_title_from(first_message),
        "created_at": now, "updated_at": now,
        "messages": [{"role": "user", "content": first_message, "kind": "user"}],
    }
    _write_conversation(project_id, conv)
    return conv


def get_conversation(project_id: str, conv_id: str) -> dict | None:
    path = _conv_path(project_id, conv_id)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return None


def save_conversation(project_id: str, conv_id: str, messages: list[dict],
                      title: str | None = None) -> dict:
    conv = get_conversation(project_id, conv_id) or {
        "id": conv_id, "title": title or "Conversation",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    conv["messages"] = list(messages)[-CONV_MAX_MESSAGES:]
    if title:
        conv["title"] = title
    conv["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_conversation(project_id, conv)
    return conv


def set_conversation_title(project_id: str, conv_id: str, title: str):
    conv = get_conversation(project_id, conv_id)
    if conv:
        conv["title"] = title
        _write_conversation(project_id, conv)


def set_conversation_pinned(project_id: str, conv_id: str, pinned: bool):
    conv = get_conversation(project_id, conv_id)
    if conv:
        conv["pinned"] = bool(pinned)
        _write_conversation(project_id, conv)


def move_conversation(src_pid: str, conv_id: str, dst_pid: str) -> bool:
    """Move a conversation file from one project (or General) to another."""
    if src_pid == dst_pid:
        return True
    conv = get_conversation(src_pid, conv_id)
    if not conv:
        return False
    _write_conversation(dst_pid, conv)
    delete_conversation(src_pid, conv_id)
    return True


def delete_conversation(project_id: str, conv_id: str):
    try:
        _conv_path(project_id, conv_id).unlink()
    except Exception:
        pass


def list_conversations(project_id: str) -> list[dict]:
    """Conversation summaries for the workspace 'Recents' list, newest first."""
    migrate_legacy_chat_history(project_id)
    d = _conv_dir(project_id)
    out = []
    if d.exists():
        for f in d.glob("*.json"):
            try:
                c = json.loads(f.read_text(encoding="utf-8"))
                ts = c.get("updated_at") or c.get("created_at") or ""
                out.append({
                    "id": c["id"], "title": c.get("title", "Conversation"),
                    "updated_at": ts, "updated_rel": relative_time(ts) if ts else "recently",
                    "pinned": bool(c.get("pinned", False)),
                    "href": f"/project/{project_id}/c/{c['id']}",
                })
            except Exception:
                continue
    out.sort(key=lambda x: (x["pinned"], x["updated_at"]), reverse=True)
    return out


def list_all_conversations(limit: int = 200) -> list[dict]:
    """All conversations across every project, newest first.

    Feeds the global sidebar 'Recents' and the Chats dashboard. Each item adds
    project_id / project_name to the per-project summary shape.
    """
    out = []
    spaces = [(p["id"], p.get("name", "Untitled")) for p in list_projects()]
    spaces.append((GENERAL_ID, GENERAL_NAME))  # include non-project chats
    for pid, pname in spaces:
        for c in list_conversations(pid):
            out.append({**c, "project_id": pid, "project_name": pname})
    out.sort(key=lambda x: (x["pinned"], x["updated_at"]), reverse=True)
    return out[:limit]


def list_all_files(limit: int = 500) -> list[dict]:
    """All KB files across every project (Artifacts library)."""
    out = []
    for p in list_projects():
        for f in list_project_files(p["id"]):
            out.append({**f, "project_name": p.get("name", "Untitled"),
                        "project_id": p["id"]})
    return out[:limit]


def generate_conversation_title(first_message: str) -> str:
    """Short Claude-style title from the first message (best-effort LLM, cheap)."""
    try:
        llm = get_llm_client()
        resp = llm.chat.completions.create(
            model=AGENT_MODEL, temperature=0.2, max_tokens=20,
            messages=[{"role": "user", "content":
                       "Summarize this request as a 3-6 word title. No quotes, no "
                       f"trailing punctuation:\n\n{first_message}"}])
        t = (resp.choices[0].message.content or "").strip().strip('"').strip()
        t = t.split("\n")[0][:60]
        return t or _conv_title_from(first_message)
    except Exception:
        return _conv_title_from(first_message)


def migrate_legacy_chat_history(project_id: str):
    """One-time fold of the old single chat_history.json into a conversation."""
    legacy = PROJECTS_DIR / project_id / "chat_history.json"
    if not legacy.exists():
        return
    has_convs = _conv_dir(project_id).exists() and any(_conv_dir(project_id).glob("*.json"))
    if not has_convs:
        try:
            msgs = json.loads(legacy.read_text(encoding="utf-8"))
            if isinstance(msgs, list) and msgs:
                first = next((m.get("content", "") for m in msgs
                              if m.get("kind") == "user"), "Imported conversation")
                now = datetime.now(timezone.utc).isoformat()
                _write_conversation(project_id, {
                    "id": uuid.uuid4().hex[:12], "title": _conv_title_from(first),
                    "created_at": now, "updated_at": now, "messages": msgs})
        except Exception:
            pass
    try:
        legacy.unlink()
    except Exception:
        pass


# --------------------------------------------------------------------------- #
#  Files / capacity
# --------------------------------------------------------------------------- #
def _file_meta(path: Path) -> dict:
    size = path.stat().st_size
    ext = path.suffix.lstrip(".").lower()
    if ext in _TEXT_EXTS:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                meta = f"{sum(1 for _ in fh)} lines"
        except Exception:
            meta = _fmt_size(size)
    else:
        meta = _fmt_size(size)
    return {"name": path.name, "meta": meta, "badge": (ext.upper() or "FILE"),
            "size": size}


def list_project_files(project_id: str) -> list[dict]:
    kb_dir = PROJECTS_DIR / project_id / "knowledge"
    if not kb_dir.exists():
        return []
    return [_file_meta(f) for f in sorted(kb_dir.glob("*")) if f.is_file()]


def project_capacity(project_id: str) -> dict:
    files = list_project_files(project_id)
    used = sum(f["size"] for f in files)
    pct = min(int(used / PROJECT_CAPACITY_BYTES * 100), 100) if PROJECT_CAPACITY_BYTES else 0
    return {"used_mb": round(used / (1024 * 1024), 1),
            "max_mb": round(PROJECT_CAPACITY_BYTES / (1024 * 1024), 1),
            "percent": pct}


def save_uploaded_file(project_id: str, filename: str, data: bytes) -> Path:
    kb_dir = PROJECTS_DIR / project_id / "knowledge"
    kb_dir.mkdir(parents=True, exist_ok=True)
    dest = kb_dir / Path(filename).name
    dest.write_bytes(data)
    return dest


# --------------------------------------------------------------------------- #
#  KB ingest (sync; no Chainlit Step) — chunk + upsert into project collection
# --------------------------------------------------------------------------- #
def _chunk_id(filename: str, idx: int, content: str) -> str:
    h = hashlib.sha256(f"{filename}:{idx}:{content[:500]}".encode()).hexdigest()[:20]
    return f"{filename}_{idx}_{h}"


def extract_text_from_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            import pdfplumber
            out = []
            with pdfplumber.open(str(path)) as pdf:
                for page in pdf.pages[:50]:
                    out.append(page.extract_text() or "")
            return "\n".join(out)
        except Exception:
            return ""
    if suffix == ".csv":
        try:
            import pandas as pd
            df = pd.read_csv(path)
            return (f"CSV {len(df)} rows, cols: {', '.join(map(str, df.columns))}\n"
                    + df.head(20).to_string(index=False))
        except Exception:
            pass
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def ingest_file_to_kb(project_id: str, path: Path) -> int:
    """Chunk a file's text and upsert into the project's ChromaDB collection."""
    text = extract_text_from_file(path)
    if not text.strip():
        return 0
    collection = get_project_kb_collection(project_id)
    chunks = [text[i:i + 2000] for i in range(0, len(text), 2000)]
    total = 0
    for i in range(0, len(chunks), 20):
        batch = chunks[i:i + 20]
        ids = [_chunk_id(f"{project_id}_{path.name}", i + j, batch[j])
               for j in range(len(batch))]
        metas = [{"source": path.name, "chunk": i + j, "type": "project_upload",
                  "project_id": project_id} for j in range(len(batch))]
        collection.upsert(documents=batch, metadatas=metas, ids=ids)
        total += len(batch)
    return total


# --------------------------------------------------------------------------- #
#  Display helpers
# --------------------------------------------------------------------------- #
def _fmt_size(n: int) -> str:
    return f"{n // 1024} KB" if n < 1024 * 1024 else f"{n / (1024 * 1024):.1f} MB"


def format_date(iso_str: str) -> str:
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return f"{dt.strftime('%b')} {dt.day}"
    except Exception:
        return "Recently"


def relative_time(value) -> str:
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        elif isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(value, tz=timezone.utc)
        else:
            dt = value
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        secs = (datetime.now(timezone.utc) - dt).total_seconds()
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
            return f"{days // 7} week{'s' if days // 7 != 1 else ''} ago"
        if days < 365:
            return f"{days // 30} month{'s' if days // 30 != 1 else ''} ago"
        return f"{days // 365} year{'s' if days // 365 != 1 else ''} ago"
    except Exception:
        return "recently"


def project_card_view(p: dict) -> dict:
    """Shape a registry entry for the dashboard card."""
    instr = get_project_instructions(p["id"])
    desc = instr.split("\n")[0].replace("#", "").strip()
    if not desc or len(desc) < 5:
        desc = "No description provided yet."
    if len(desc) > 80:
        desc = desc[:77] + "…"
    return {"id": p["id"], "name": p.get("name", "Untitled"),
            "updated": format_date(p.get("created_at", "")), "desc": desc,
            "href": f"/project/{p['id']}"}


# =========================================================================== #
#  BigQuery + schema catalog + SQL execution  (domain layer, UI-agnostic)
# =========================================================================== #
PROJECT_ID = os.getenv("GCP_PROJECT_ID", "ajgc-dig-jjc-prod-jawacloud-01")
_GB = 1024 ** 3
MAX_BYTES_BILLED = int(float(os.getenv("MAX_BYTES_BILLED_GB", "100")) * _GB)
QUERY_TIMEOUT_SEC = int(os.getenv("QUERY_TIMEOUT_SEC", "300"))
MAX_RETURN_ROWS = 50          # rows handed back to the LLM
MAX_STORED_ROWS = 5000        # rows materialised in memory
MAX_COLS_PER_CARD = 200
MAX_TABLE_ROWS_UI = 50        # rows rendered in the chat table

CATALOG_DATASETS = [
    d.strip() for d in os.getenv(
        "CATALOG_DATASETS",
        "aj360,aj360_platform,aj360_search_analytics,"
        "al_jazeera_data_models,aj360_ds,aj360_monitoring,"
        "aj360_marts,aj360_acquisition_analytics",
    ).split(",") if d.strip()
]
_CATALOG_VERSION = hashlib.md5(",".join(sorted(CATALOG_DATASETS)).encode()).hexdigest()[:12]
_CATALOG_VERSION_FILE = KNOWLEDGE_DIR / ".catalog_version"

GENERIC_COLS = {
    "date", "name", "value", "type", "key", "status", "id", "count", "total",
    "country", "city", "region", "month", "week", "weekday", "source", "medium",
    "device", "category", "title", "description", "label", "url", "hour", "day",
}
BANNED_ALIASES = {"rows", "range", "groups", "current", "all", "order",
                  "partition", "window", "over", "rollup", "hash"}

VISION_MODEL = os.getenv("VISION_MODEL", "glm-4v-plus")

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


# ---- LLM client (ZhipuAI / GLM) ---- #
_llm_client = None
_llm_lock = threading.Lock()


def get_llm_client():
    global _llm_client
    with _llm_lock:
        if _llm_client is None:
            from zhipuai import ZhipuAI
            _llm_client = ZhipuAI(api_key=os.getenv("ZHIPU_API_KEY"))
        return _llm_client


# ---- ChromaDB catalog collections (shared with the Chainlit app) ---- #
def _schema_catalog():
    return _get_chroma().get_or_create_collection("schema_catalog")


def _kb_documents():
    return _get_chroma().get_or_create_collection("kb_documents")


# --------------------------------------------------------------------------- #
#  Schema catalog build (sync; callers wrap in asyncio.to_thread)
# --------------------------------------------------------------------------- #
def _flatten_fields(fields, prefix=""):
    out = []
    for f in fields:
        name = f"{prefix}{f.name}"
        out.append((name, f.field_type, f.mode or "NULLABLE"))
        if f.field_type == "RECORD" and f.fields:
            out.extend(_flatten_fields(f.fields, prefix=name + "."))
    return out


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
# --------------------------------------------------------------------------- #
def search_project_kb(project_id: str, question: str, top_k: int = 5) -> str:
    try:
        coll = get_project_kb_collection(project_id)
        if coll.count() > 0:
            docs = coll.query(query_texts=[question], n_results=top_k)
            if docs.get("documents") and docs["documents"][0]:
                return "\n\n---\n\n".join(docs["documents"][0])
    except Exception:
        pass
    return ""


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
def fmt_bytes(n) -> str:
    if not n:
        return "0 B"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024


def _check_banned_aliases(sql: str) -> str | None:
    aliases = set()
    for m in re.finditer(r"\bAS\s+(\w+)", sql, re.IGNORECASE):
        aliases.add(m.group(1).lower())
    keywords = {"select", "from", "where", "group", "order", "having", "limit",
                "union", "intersect", "except", "on", "and", "or", "not", "left",
                "right", "inner", "outer", "cross", "full", "join", "into"}
    for m in re.finditer(r"\)\s+(\w+)", sql):
        w = m.group(1).lower()
        if w not in keywords:
            aliases.add(w)
    hits = aliases & BANNED_ALIASES
    if hits:
        return (f"Banned alias(es): {', '.join(sorted(hits))}. BigQuery reserves these. "
                f"Rename them.")
    return None


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

    alias_err = _check_banned_aliases(sql)
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
