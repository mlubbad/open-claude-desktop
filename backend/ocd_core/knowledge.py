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


def chunk_text(text: str, size: int = 1200, overlap: int = 200) -> list[str]:
    """Split text into overlapping, boundary-aware chunks for retrieval.

    Prefers to break on paragraph then sentence boundaries so a chunk rarely cuts a
    sentence in half, packs pieces up to ``size`` characters, and carries ``overlap``
    characters of tail context into the next chunk so a fact spanning a boundary stays
    findable. A single oversized paragraph is hard-split. Pure + deterministic.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    overlap = max(0, min(overlap, size // 2))

    # Split into paragraphs, then over-long paragraphs into sentences, then hard-wrap
    # anything still longer than `size`.
    import re
    pieces: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if len(para) <= size:
            pieces.append(para)
            continue
        for sent in re.split(r"(?<=[.!?])\s+", para):
            sent = sent.strip()
            if not sent:
                continue
            while len(sent) > size:
                pieces.append(sent[:size])
                sent = sent[size:]
            if sent:
                pieces.append(sent)

    # Pack pieces (each already <= size) into chunks of at most `size` chars. On a flush,
    # seed the next chunk with the previous chunk's tail (overlap) when it still fits, so
    # boundary context carries over without ever exceeding `size`.
    chunks: list[str] = []
    cur = ""
    for piece in pieces:
        candidate = f"{cur}\n{piece}".strip() if cur else piece
        if len(candidate) <= size:
            cur = candidate
            continue
        if cur:
            chunks.append(cur)
        tail = chunks[-1][-overlap:] if (chunks and overlap) else ""
        seeded = f"{tail}\n{piece}".strip() if tail else piece
        cur = seeded if len(seeded) <= size else piece
    if cur:
        chunks.append(cur)
    return chunks


def ingest_file_to_kb(project_id: str, path: Path) -> int:
    """Chunk a file's text and upsert into the project's ChromaDB collection."""
    text = extract_text_from_file(path)
    if not text.strip():
        return 0
    collection = get_project_kb_collection(project_id)
    chunks = chunk_text(text)
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
def search_project_kb_sources(project_id: str, question: str, top_k: int = 5) -> list[dict]:
    """Structured KB hits: [{source, chunk, text, score}], best first. score is a 0..1
    relevance (1 - cosine distance) when the backend reports distances."""
    try:
        coll = get_project_kb_collection(project_id)
        if coll.count() == 0:
            return []
        res = coll.query(query_texts=[question], n_results=top_k)
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        out: list[dict] = []
        for i, doc in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            dist = dists[i] if i < len(dists) else None
            out.append({
                "source": (meta or {}).get("source", "document"),
                "chunk": (meta or {}).get("chunk", i),
                "text": doc,
                "score": (round(max(0.0, 1.0 - float(dist)), 3) if dist is not None else None),
            })
        return out
    except Exception:
        return []


def search_project_kb(project_id: str, question: str, top_k: int = 5) -> str:
    """Cited KB context for the agent to read + attribute. Each passage is headed by its
    source so the model can say where a fact came from (Claude-style citations)."""
    hits = search_project_kb_sources(project_id, question, top_k)
    if not hits:
        return ""
    blocks = [f"[{h['source']} · chunk {h['chunk']}]\n{h['text']}" for h in hits]
    return "\n\n---\n\n".join(blocks)
