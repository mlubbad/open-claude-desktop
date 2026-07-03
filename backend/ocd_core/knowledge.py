"""Project knowledge: files (list/save/meta) + KB ingest/search.

Moved verbatim from aj360_app/aj360_app/core.py. Behavior parity is the
contract; only import references were adjusted (util.fmt_size for _fmt_size,
util.chunk_id for _chunk_id, ocd_core.chroma for the KB collection, and
projects.list_projects for the cross-project aggregate). extract_text_from_file
does not touch the LLM (pdfplumber / pandas / plain read), matching the
original.
"""
from __future__ import annotations

from pathlib import Path

from . import config, util
from .chroma import get_project_kb_collection

# Matches core.py: extensions whose _file_meta reports a line count.
_TEXT_EXTS = {"sql", "md", "txt", "csv", "json", "py", "yaml", "yml", "log"}


# --------------------------------------------------------------------------- #
#  Files / capacity
# --------------------------------------------------------------------------- #
def _file_meta(path: Path) -> dict:
    size = path.stat().st_size
    ext = path.suffix.lstrip(".").lower()
    if ext in _TEXT_EXTS:
        try:
            with open(path, encoding="utf-8", errors="ignore") as fh:
                meta = f"{sum(1 for _ in fh)} lines"
        except Exception:
            meta = util.fmt_size(size)
    else:
        meta = util.fmt_size(size)
    return {"name": path.name, "meta": meta, "badge": (ext.upper() or "FILE"),
            "size": size}


def list_project_files(project_id: str) -> list[dict]:
    kb_dir = config.PROJECTS_DIR / project_id / "knowledge"
    if not kb_dir.exists():
        return []
    return [_file_meta(f) for f in sorted(kb_dir.glob("*")) if f.is_file()]


def save_uploaded_file(project_id: str, filename: str, data: bytes) -> Path:
    kb_dir = config.PROJECTS_DIR / project_id / "knowledge"
    kb_dir.mkdir(parents=True, exist_ok=True)
    dest = kb_dir / Path(filename).name
    dest.write_bytes(data)
    return dest


def list_all_files(limit: int = 500) -> list[dict]:
    """All KB files across every project (Artifacts library)."""
    from .projects import list_projects
    out = []
    for p in list_projects():
        for f in list_project_files(p["id"]):
            out.append({**f, "project_name": p.get("name", "Untitled"),
                        "project_id": p["id"]})
    return out[:limit]


# --------------------------------------------------------------------------- #
#  KB ingest (sync; no Chainlit Step) — chunk + upsert into project collection
# --------------------------------------------------------------------------- #
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
        ids = [util.chunk_id(f"{project_id}_{path.name}", i + j, batch[j])
               for j in range(len(batch))]
        metas = [{"source": path.name, "chunk": i + j, "type": "project_upload",
                  "project_id": project_id} for j in range(len(batch))]
        collection.upsert(documents=batch, metadatas=metas, ids=ids)
        total += len(batch)
    return total


# --------------------------------------------------------------------------- #
#  Project KB search (isolated per-project collection)
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
