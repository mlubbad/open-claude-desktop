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
    # Double-checked locking (unlike the lock-always get_llm_client /
    # get_bq_client) so concurrent first-callers don't each build a
    # PersistentClient.
    global _chroma
    if _chroma is None:
        with _chroma_lock:
            if _chroma is None:
                import chromadb
                _chroma = chromadb.PersistentClient(path=config.CHROMA_PATH)
    return _chroma


def _scoped_collection_name(base: str) -> str:
    """Namespace a ChromaDB collection by the current workspace so tenants' vectors never
    share a collection. Local-first / flag-off and the `local` workspace keep the exact
    historical name (so existing embeddings are still found); a non-local tenant gets a
    stable, charset-safe, length-bounded prefix. Project KB is already isolated by the
    globally-unique project slug — this is defense-in-depth that doesn't rely on that
    invariant. Both create and delete must route through here so the names always match."""
    from . import tenancy
    ns = tenancy.namespace()
    if not ns:
        return base
    import hashlib
    # A hashed workspace prefix keeps the name inside ChromaDB's charset + 63-char cap
    # regardless of the raw workspace id; the base is hashed too only if it would overflow.
    prefix = "w" + hashlib.sha1(ns.encode()).hexdigest()[:10]
    name = f"{prefix}_{base}"
    if len(name) > 63:
        name = f"{prefix}_{hashlib.sha1(base.encode()).hexdigest()[:16]}"
    return name


def project_kb_collection_name(project_id: str) -> str:
    """The (workspace-scoped) collection name for a project's knowledge base. Callers that
    create/delete the collection outside this module use this so names stay consistent."""
    return _scoped_collection_name(f"kb_project_{project_id}")


def get_project_kb_collection(project_id: str):
    return _get_chroma().get_or_create_collection(project_kb_collection_name(project_id))
