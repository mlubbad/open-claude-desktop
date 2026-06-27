"""Lazy ChromaDB client accessor shared by both app surfaces.

Moved verbatim from aj360_app/aj360_app/core.py (the client singleton + the
per-project KB collection helper). The schema-catalog / kb_documents COLLECTIONS
stay in core.py for now and import _get_chroma from here. Behavior parity is the
contract — do NOT change the logic.
"""
from __future__ import annotations

import threading

from . import config

# --------------------------------------------------------------------------- #
#  Lazy ChromaDB (only touched for file ingest / KB search, not for listing)
# --------------------------------------------------------------------------- #
_chroma = None
_chroma_lock = threading.Lock()


def _get_chroma():
    # Double-checked locking (mirrors llm.get_llm_client / bigquery.get_bq_client)
    # so concurrent first-callers don't each build a PersistentClient.
    global _chroma
    if _chroma is None:
        with _chroma_lock:
            if _chroma is None:
                import chromadb
                _chroma = chromadb.PersistentClient(path=config.CHROMA_PATH)
    return _chroma


def get_project_kb_collection(project_id: str):
    return _get_chroma().get_or_create_collection(f"kb_project_{project_id}")
