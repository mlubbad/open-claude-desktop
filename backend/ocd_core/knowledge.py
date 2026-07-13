"""Project knowledge: files (list/save/meta) + KB ingest/search.

Moved verbatim from aj360_app/aj360_app/core.py. Behavior parity is the
contract; only import references were adjusted (util.fmt_size for _fmt_size,
util.chunk_id for _chunk_id, ocd_core.chroma for the KB collection, and
projects.list_projects for the cross-project aggregate). extract_text_from_file
does not touch the LLM (pdfplumber / pandas / plain read), matching the
original.
"""
from __future__ import annotations

import os
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
#  KB ingest — chunk + upsert into project collection
# --------------------------------------------------------------------------- #
class ExtractionError(Exception):
    """A file type we DO understand failed to parse. Raised (not swallowed) so the
    upload route can tell the user their document didn't ingest, instead of the old
    behavior of silently indexing nothing."""


# One pathological file must not flood the KB or the ingest loop.
_MAX_EXTRACT_CHARS = 2_000_000
_PDF_MAX_PAGES = 300

# Hard cap on a single uploaded file (bytes) — a multi-GB upload must never be slurped
# whole into memory. Overridable via env.
MAX_UPLOAD_BYTES = int(os.getenv("OCD_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024)))
# Cap on the DECOMPRESSED bytes read from any single ZIP member (docx/pptx/xlsx are
# zips): a small "zip bomb" member can otherwise expand to gigabytes.
_MAX_ZIP_MEMBER_BYTES = int(os.getenv("OCD_MAX_ZIP_MEMBER_BYTES", str(50 * 1024 * 1024)))


class UploadTooLarge(Exception):
    """An uploaded file exceeds MAX_UPLOAD_BYTES."""


def read_upload(file_obj, limit: int | None = None) -> bytes:
    """Read an upload's bytes under a hard cap: read limit+1 and reject on overflow, so a
    huge upload can't exhaust memory before we ever touch it."""
    limit = MAX_UPLOAD_BYTES if limit is None else limit
    data = file_obj.read(limit + 1)
    if len(data) > limit:
        raise UploadTooLarge(f"file exceeds the {limit // (1024 * 1024)} MB upload limit")
    return data


def _read_zip_member(z, name: str) -> bytes:
    """Read a ZIP member's DECOMPRESSED bytes under a cap. zipfile decompresses
    incrementally, so reading limit+1 never expands the whole member into memory — the
    zip-bomb guard for Office (docx/pptx/xlsx) extraction."""
    with z.open(name) as fh:
        data = fh.read(_MAX_ZIP_MEMBER_BYTES + 1)
    if len(data) > _MAX_ZIP_MEMBER_BYTES:
        raise ExtractionError(
            f"'{name}' expands beyond the {_MAX_ZIP_MEMBER_BYTES // (1024 * 1024)} MB limit")
    return data

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _num_key(name: str) -> int:
    import re
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else 0


def _docx_text(path: Path) -> str:
    import xml.etree.ElementTree as ET
    import zipfile
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(_read_zip_member(z, "word/document.xml"))
    paras = []
    for p in root.iter(f"{_W}p"):
        runs = "".join(t.text or "" for t in p.iter(f"{_W}t"))
        if runs.strip():
            paras.append(runs)
    return "\n".join(paras)


def _pptx_text(path: Path) -> str:
    import re
    import xml.etree.ElementTree as ET
    import zipfile
    out = []
    with zipfile.ZipFile(path) as z:
        slides = sorted((n for n in z.namelist()
                         if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=_num_key)
        for i, name in enumerate(slides, 1):
            root = ET.fromstring(_read_zip_member(z, name))
            texts = [t.text or "" for t in root.iter(f"{_A}t") if (t.text or "").strip()]
            if texts:
                out.append(f"[slide {i}]\n" + "\n".join(texts))
    return "\n\n".join(out)


def _xlsx_text(path: Path) -> str:
    import re
    import xml.etree.ElementTree as ET
    import zipfile
    with zipfile.ZipFile(path) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            sroot = ET.fromstring(_read_zip_member(z, "xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in si.iter(f"{_S}t"))
                      for si in sroot.iter(f"{_S}si")]
        sheets = sorted((n for n in z.namelist()
                         if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", n)), key=_num_key)
        out = []
        for name in sheets:
            root = ET.fromstring(_read_zip_member(z, name))
            rows = []
            for row in root.iter(f"{_S}row"):
                cells = []
                for c in row.iter(f"{_S}c"):
                    v = c.find(f"{_S}v")
                    if v is not None and v.text is not None:
                        if c.get("t") == "s":  # shared-string reference
                            try:
                                cells.append(shared[int(v.text)])
                            except (ValueError, IndexError):
                                cells.append(v.text)
                        else:
                            cells.append(v.text)
                    else:  # inline string cell
                        inline = c.find(f"{_S}is")
                        cells.append("".join(t.text or "" for t in inline.iter(f"{_S}t"))
                                     if inline is not None else "")
                if any(x.strip() for x in cells):
                    rows.append("\t".join(cells))
            if rows:
                out.append("\n".join(rows))
    return "\n\n".join(out)


def _html_text(path: Path) -> str:
    from html.parser import HTMLParser

    class _Text(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts: list[str] = []
            self._skip = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style"):
                self._skip += 1

        def handle_endtag(self, tag):
            if tag in ("script", "style"):
                self._skip = max(0, self._skip - 1)

        def handle_data(self, data):
            if not self._skip and data.strip():
                self.parts.append(data.strip())

    p = _Text()
    p.feed(path.read_text(encoding="utf-8", errors="ignore"))
    return "\n".join(p.parts)


def _rtf_text(path: Path) -> str:
    import re
    raw = path.read_text(encoding="utf-8", errors="ignore")
    raw = re.sub(r"\\'[0-9a-fA-F]{2}", " ", raw)    # hex escapes
    raw = re.sub(r"\\[a-zA-Z]+-?\d*\s?", " ", raw)  # control words
    raw = raw.replace("{", " ").replace("}", " ").replace("\\", " ")
    return re.sub(r"[ \t]{2,}", " ", raw).strip()


def _csv_text(path: Path) -> str:
    import csv as _csv
    with open(path, newline="", encoding="utf-8", errors="ignore") as fh:
        return "\n".join(", ".join(row) for row in _csv.reader(fh))


def extract_text_from_file(path: Path) -> str:
    """Text of a knowledge file for chunking. Office formats (docx/xlsx/pptx) are read
    with the stdlib (zip + XML) — no heavyweight parser dependencies; html/rtf/csv are
    handled in full; PDFs via pdfplumber. A structured format that fails to parse
    raises ExtractionError (surfaced to the uploader); anything unrecognized falls
    back to a plain text read."""
    suffix = path.suffix.lower()
    handlers = {".docx": _docx_text, ".pptx": _pptx_text, ".xlsx": _xlsx_text,
                ".html": _html_text, ".htm": _html_text, ".rtf": _rtf_text,
                ".csv": _csv_text}
    if suffix == ".pdf":
        try:
            import pdfplumber
            out = []
            with pdfplumber.open(str(path)) as pdf:
                for page in pdf.pages[:_PDF_MAX_PAGES]:
                    out.append(page.extract_text() or "")
            return "\n".join(out)[:_MAX_EXTRACT_CHARS]
        except Exception as e:
            raise ExtractionError(f"could not read PDF: {e}") from e
    if suffix in handlers:
        try:
            return handlers[suffix](path)[:_MAX_EXTRACT_CHARS]
        except ExtractionError:
            raise
        except Exception as e:
            raise ExtractionError(
                f"could not parse {suffix.lstrip('.')} file: {e}") from e
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:_MAX_EXTRACT_CHARS]
    except OSError as e:
        raise ExtractionError(f"could not read file: {e}") from e


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


def delete_project_file(project_id: str, name: str) -> bool:
    """Delete ONE knowledge file and purge its chunks from the project's KB (P1-11).
    Previously only deleting the whole project dropped the collection, so removing a
    single file left orphaned vectors that kept matching searches."""
    import contextlib
    kb_dir = (config.PROJECTS_DIR / project_id / "knowledge").resolve()
    dest = (kb_dir / Path(name).name).resolve()
    if dest.parent != kb_dir or not dest.is_file():
        return False
    dest.unlink()
    with contextlib.suppress(Exception):  # missing collection = nothing to purge
        get_project_kb_collection(project_id).delete(where={"source": Path(name).name})
    return True


def reindex_project_file(project_id: str, name: str) -> int:
    """Re-ingest ONE knowledge file: purge its old chunks, then chunk + embed afresh
    (e.g. after an extraction fix). Returns the new chunk count; raises
    ExtractionError like ingest. Returns -1 if the file doesn't exist."""
    import contextlib
    kb_dir = (config.PROJECTS_DIR / project_id / "knowledge").resolve()
    path = (kb_dir / Path(name).name).resolve()
    if path.parent != kb_dir or not path.is_file():
        return -1
    with contextlib.suppress(Exception):
        get_project_kb_collection(project_id).delete(where={"source": path.name})
    return ingest_file_to_kb(project_id, path)


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
