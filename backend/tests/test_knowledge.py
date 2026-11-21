"""Tests for ocd_core.knowledge — files + KB ingest/search.

Text extraction for .txt/.csv is exercised for real (no mocks). The ChromaDB
ingest->search round-trip is attempted for real against a tmp CHROMA_PATH; if
the embedding backend is unavailable in this environment it degrades to an
import-smoke and is skipped (noted), keeping the suite fast and deterministic.
"""
import importlib

import pytest


def _reload(tmp_path, monkeypatch):
    monkeypatch.setenv("OCD_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CHROMA_PATH", str(tmp_path / "chroma_db"))
    cfg = importlib.reload(importlib.import_module("ocd_core.config"))
    # chroma snapshots nothing path-wise but reads config.CHROMA_PATH live;
    # reload it too so the singleton resets between tests.
    importlib.reload(importlib.import_module("ocd_core.chroma"))
    know = importlib.reload(importlib.import_module("ocd_core.knowledge"))
    return cfg, know


def test_extract_text_from_txt(tmp_path, monkeypatch):
    _cfg, know = _reload(tmp_path, monkeypatch)
    f = tmp_path / "note.txt"
    f.write_text("hello world\nsecond line", encoding="utf-8")
    assert know.extract_text_from_file(f) == "hello world\nsecond line"


def test_extract_text_from_csv(tmp_path, monkeypatch):
    _cfg, know = _reload(tmp_path, monkeypatch)
    f = tmp_path / "data.csv"
    f.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    out = know.extract_text_from_file(f)
    # P0-5: the FULL CSV is ingested (header + every row), not a 20-row preview.
    assert out.splitlines() == ["a, b", "1, 2", "3, 4"]


def test_list_project_files_and_capacity(tmp_path, monkeypatch):
    cfg, know = _reload(tmp_path, monkeypatch)
    kb = cfg.PROJECTS_DIR / "p1" / "knowledge"
    kb.mkdir(parents=True, exist_ok=True)
    (kb / "a.txt").write_text("one\ntwo\nthree", encoding="utf-8")
    (kb / "b.sql").write_text("SELECT 1", encoding="utf-8")

    files = know.list_project_files("p1")
    names = {f["name"] for f in files}
    assert names == {"a.txt", "b.sql"}
    # text files report a line count as meta.
    a = next(f for f in files if f["name"] == "a.txt")
    assert a["meta"] == "3 lines"
    assert a["badge"] == "TXT"

    # project_capacity lives in ocd_core.projects but reads list_project_files
    # from knowledge — exercise the cross-module wiring here.
    projects = importlib.reload(importlib.import_module("ocd_core.projects"))
    cap = projects.project_capacity("p1")
    assert cap["percent"] >= 0 and cap["used_mb"] >= 0


def test_save_uploaded_file(tmp_path, monkeypatch):
    cfg, know = _reload(tmp_path, monkeypatch)
    dest = know.save_uploaded_file("p2", "report.txt", b"payload")
    assert dest.read_bytes() == b"payload"
    assert dest.parent == cfg.PROJECTS_DIR / "p2" / "knowledge"


def test_list_all_files_aggregates(tmp_path, monkeypatch, db):
    cfg, know = _reload(tmp_path, monkeypatch)
    # Needs a real project in the (DB-backed) registry to be aggregated.
    projects = importlib.reload(importlib.import_module("ocd_core.projects"))
    projects.create_project("Proj X")
    know.save_uploaded_file("proj-x", "f.txt", b"hi")
    allf = know.list_all_files()
    assert any(f["name"] == "f.txt" and f["project_id"] == "proj-x" for f in allf)


def test_kb_ingest_search_roundtrip(tmp_path, monkeypatch):
    _cfg, know = _reload(tmp_path, monkeypatch)
    # search on an empty/absent collection returns "".
    assert know.search_project_kb("p3", "anything") == ""

    f = tmp_path / "doc.txt"
    f.write_text("The annual revenue for 2024 was forty two million dollars.",
                 encoding="utf-8")
    try:
        n = know.ingest_file_to_kb("p3", f)
    except Exception as e:  # embedding backend unavailable offline
        pytest.skip(f"ChromaDB ingest unavailable in this env: {e}")
    assert n >= 1
    hit = know.search_project_kb("p3", "revenue")
    assert "revenue" in hit.lower()
    # Cited: the passage is attributed to its source file + chunk index.
    assert "[doc.txt" in hit
    # Structured variant carries source + text (+ a score when distances are reported).
    srcs = know.search_project_kb_sources("p3", "revenue")
    assert srcs and srcs[0]["source"] == "doc.txt"
    assert "revenue" in srcs[0]["text"].lower()


def test_chunk_text_short_text_is_one_chunk(tmp_path, monkeypatch):
    _cfg, know = _reload(tmp_path, monkeypatch)
    assert know.chunk_text("hello world") == ["hello world"]
    assert know.chunk_text("") == []
    assert know.chunk_text("   ") == []


def test_chunk_text_respects_size_and_overlaps(tmp_path, monkeypatch):
    _cfg, know = _reload(tmp_path, monkeypatch)
    # Many short paragraphs -> multiple chunks, each within size.
    text = "\n\n".join(f"Paragraph number {i} with some filler words here." for i in range(60))
    chunks = know.chunk_text(text, size=300, overlap=60)
    assert len(chunks) > 1
    assert all(len(c) <= 300 for c in chunks)  # never exceeds size
    # Consecutive chunks share a tail/prefix (overlap) -> boundary context preserved.
    assert any(chunks[i][-20:] and chunks[i][-20:] in chunks[i + 1] for i in range(len(chunks) - 1))


def test_chunk_text_hard_splits_a_giant_paragraph(tmp_path, monkeypatch):
    _cfg, know = _reload(tmp_path, monkeypatch)
    giant = "x" * 5000  # one paragraph, no sentence breaks
    chunks = know.chunk_text(giant, size=1000, overlap=100)
    assert len(chunks) >= 5
    assert all(len(c) <= 1000 for c in chunks)


def test_chunk_text_prefers_paragraph_boundaries(tmp_path, monkeypatch):
    _cfg, know = _reload(tmp_path, monkeypatch)
    a = "A" * 200
    b = "B" * 200
    chunks = know.chunk_text(f"{a}\n\n{b}", size=250, overlap=0)
    # Two ~200-char paragraphs don't fit together in 250, so they land in separate chunks
    # without cutting either paragraph in half.
    assert a in "".join(chunks) and b in "".join(chunks)
    assert any(a in c and b not in c for c in chunks)
