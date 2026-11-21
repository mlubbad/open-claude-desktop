"""Pluggable object storage for uploaded files (hosted-SaaS slice 4b).

OFF by default. `OCD_BLOB_BACKEND` unset or ``local`` selects `LocalBlobStore`, a
transparent pass-through over the historical on-disk layout
(``REPO_ROOT/projects/<pid>/knowledge/<name>``), so the packaged desktop is
byte-for-byte unchanged — same paths, same bytes, no new dependency.

Flip ``OCD_BLOB_BACKEND=s3`` for a hosted, multi-node deploy: raw upload bytes
then live in an S3-compatible bucket (``OCD_S3_BUCKET`` + the usual AWS
env/instance credentials, optional ``OCD_S3_ENDPOINT`` for MinIO/R2), while each
node keeps an ephemeral local cache under ``REPO_ROOT/.blobcache`` so the
path-based consumers (pdfplumber / pandas extraction, the code-exec knowledge
mirror) keep working against a real file without being rewritten. boto3 is a
lazy, optional import — only needed when the S3 backend is actually selected.

Keys are workspace-namespaced when tenancy is enforcing (defense in depth,
mirroring chroma / settings / secrets); for the ``local`` workspace or with the
flag off the key is unprefixed, so existing data keeps its exact path.

The abstraction is deliberately small — put / get / delete / exists / size /
list, plus two "give me a real filesystem path" escapes (`local_path` for one
key, `local_dir` for a prefix) that the extractors need. Everything the product
does with an upload is expressible over this surface.
"""
from __future__ import annotations

import os
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from . import config, tenancy


# --------------------------------------------------------------------------- #
#  Key namespacing (workspace isolation, defense in depth)
# --------------------------------------------------------------------------- #
def _ns_key(key: str) -> str:
    """Prefix a logical key with the active workspace when tenancy is enforcing.

    Local workspace / flag-off → returned unchanged, so pre-tenancy data keeps
    its historical path. The prefix is charset-safe (workspace ids are slugs)."""
    key = key.lstrip("/")
    ns = tenancy.namespace()
    return f"{ns}/{key}" if ns else key


# --------------------------------------------------------------------------- #
#  Interface
# --------------------------------------------------------------------------- #
class BlobStore(ABC):
    """A minimal object store over logical keys like ``projects/<pid>/knowledge/x``."""

    #: True for backends whose bytes already live on the local filesystem, so a
    #: line-count / stat on `local_path` is free (no download). Callers use this
    #: to avoid materializing remote objects just to compute cheap metadata.
    is_local: bool = False

    @abstractmethod
    def put(self, key: str, data: bytes) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def delete(self, key: str) -> bool:
        """Remove the object; return True if it existed."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def size(self, key: str) -> int:
        """Object size in bytes, or -1 if it does not exist."""

    @abstractmethod
    def list(self, prefix: str) -> list[str]:
        """Full keys of the objects directly under ``prefix`` (files only), sorted."""

    @abstractmethod
    def local_path(self, key: str) -> Path:
        """A real filesystem path holding the object's current bytes.

        Local backend: the canonical file. Remote backend: an ephemeral cache
        copy, downloaded/refreshed on demand. Callers that only need the bytes
        should prefer ``get`` — this exists for path-only libraries (pdfplumber,
        pandas) and the code-exec mirror."""

    @abstractmethod
    def local_dir(self, prefix: str) -> Path:
        """A real filesystem directory containing every object under ``prefix``.

        Local backend: the canonical directory. Remote backend: a cache dir
        populated from ``list`` + download. Used by the code-exec knowledge
        mirror, which iterates a project's uploaded files."""


# --------------------------------------------------------------------------- #
#  Local (default) — filesystem pass-through, byte-for-byte unchanged desktop
# --------------------------------------------------------------------------- #
class LocalBlobStore(BlobStore):
    is_local = True

    def __init__(self, root: Path | None = None) -> None:
        # None → resolve lazily from config on every access, so a cached store still
        # honors a monkeypatched PROJECTS_DIR (tests) or a PROJECTS_DIR env override.
        self._root_override = Path(root) if root is not None else None

    @property
    def _root(self) -> Path:
        # The projects PARENT is the data root: a logical key like
        # "<projects>/<pid>/knowledge/<name>" then resolves onto config.PROJECTS_DIR
        # exactly (== REPO_ROOT in a normal deploy), keeping the historical layout.
        return self._root_override or config.PROJECTS_DIR.parent

    def _abs(self, key: str) -> Path:
        # Resolve under the root and refuse any key that escapes it (a ".." or an
        # absolute component must never reach a host path outside the data root).
        p = (self._root / _ns_key(key)).resolve()
        root = self._root.resolve()
        if p != root and root not in p.parents:
            raise ValueError(f"blob key escapes storage root: {key!r}")
        return p

    def put(self, key: str, data: bytes) -> None:
        dest = self._abs(key)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)

    def get(self, key: str) -> bytes:
        return self._abs(key).read_bytes()

    def delete(self, key: str) -> bool:
        p = self._abs(key)
        if p.is_file():
            p.unlink()
            return True
        return False

    def exists(self, key: str) -> bool:
        return self._abs(key).is_file()

    def size(self, key: str) -> int:
        p = self._abs(key)
        return p.stat().st_size if p.is_file() else -1

    def list(self, prefix: str) -> list[str]:
        base = self._abs(prefix.rstrip("/"))
        if not base.is_dir():
            return []
        pfx = prefix.rstrip("/")
        return sorted(f"{pfx}/{f.name}" for f in base.iterdir() if f.is_file())

    def local_path(self, key: str) -> Path:
        return self._abs(key)

    def local_dir(self, prefix: str) -> Path:
        return self._abs(prefix.rstrip("/"))


# --------------------------------------------------------------------------- #
#  S3 (opt-in) — bucket-backed with a per-node local cache
# --------------------------------------------------------------------------- #
class S3BlobStore(BlobStore):
    is_local = False

    def __init__(self, bucket: str | None = None, prefix: str = "",
                 endpoint: str | None = None, cache_root: Path | None = None,
                 client=None) -> None:
        self._bucket = bucket or os.getenv("OCD_S3_BUCKET", "")
        if not self._bucket:
            raise RuntimeError("OCD_S3_BUCKET must be set for the s3 blob backend")
        # An optional key prefix inside the bucket, so many deployments can share one.
        self._prefix = (prefix or os.getenv("OCD_S3_PREFIX", "")).strip("/")
        self._cache = Path(cache_root or (config.REPO_ROOT / ".blobcache"))
        self._lock = threading.Lock()
        if client is not None:
            self._client = client
        else:
            try:
                import boto3  # lazy: only needed when S3 is actually selected
            except ImportError as e:  # pragma: no cover - import-guard
                raise RuntimeError(
                    "the s3 blob backend needs boto3 (pip install boto3)") from e
            self._client = boto3.client(
                "s3", endpoint_url=endpoint or os.getenv("OCD_S3_ENDPOINT") or None)

    def _s3key(self, key: str) -> str:
        k = _ns_key(key)
        return f"{self._prefix}/{k}" if self._prefix else k

    def _cache_path(self, key: str) -> Path:
        # Mirror the logical (namespaced) key under the cache root so a cached file
        # for workspace A never collides with the same logical name in workspace B.
        p = (self._cache / _ns_key(key)).resolve()
        root = self._cache.resolve()
        if root not in p.parents:
            raise ValueError(f"blob key escapes cache root: {key!r}")
        return p

    def put(self, key: str, data: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=self._s3key(key), Body=data)
        # Keep the local cache coherent so a subsequent local_path is a cache hit.
        cp = self._cache_path(key)
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_bytes(data)

    def get(self, key: str) -> bytes:
        resp = self._client.get_object(Bucket=self._bucket, Key=self._s3key(key))
        return resp["Body"].read()

    def delete(self, key: str) -> bool:
        existed = self.exists(key)
        self._client.delete_object(Bucket=self._bucket, Key=self._s3key(key))
        cp = self._cache_path(key)
        if cp.is_file():
            cp.unlink()
        return existed

    def exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=self._s3key(key))
            return True
        except Exception:  # noqa: BLE001 - any head failure means "not present"
            return False

    def size(self, key: str) -> int:
        try:
            h = self._client.head_object(Bucket=self._bucket, Key=self._s3key(key))
            return int(h.get("ContentLength", -1))
        except Exception:  # noqa: BLE001
            return -1

    def list(self, prefix: str) -> list[str]:
        pfx = prefix.rstrip("/") + "/"
        s3pfx = self._s3key(pfx)
        out: list[str] = []
        token = None
        # Strip both the bucket prefix and the workspace namespace back off, so the
        # caller gets the same LOGICAL keys it passed in.
        drop = self._s3key("")  # namespace (+ bucket prefix) applied to an empty key
        while True:
            kw = {"Bucket": self._bucket, "Prefix": s3pfx, "Delimiter": "/"}
            if token:
                kw["ContinuationToken"] = token
            resp = self._client.list_objects_v2(**kw)
            for obj in resp.get("Contents", []) or []:
                k = obj["Key"]
                logical = k[len(drop):] if drop and k.startswith(drop) else k
                if logical != pfx.rstrip("/"):  # skip a directory-marker object
                    out.append(logical)
            if resp.get("IsTruncated"):
                token = resp.get("NextContinuationToken")
            else:
                break
        return sorted(out)

    def local_path(self, key: str) -> Path:
        cp = self._cache_path(key)
        with self._lock:
            # Refresh the cache when missing or stale (size mismatch is a cheap proxy).
            if not cp.is_file() or cp.stat().st_size != self.size(key):
                cp.parent.mkdir(parents=True, exist_ok=True)
                cp.write_bytes(self.get(key))
        return cp

    def local_dir(self, prefix: str) -> Path:
        base = self._cache_path(prefix.rstrip("/"))
        base.mkdir(parents=True, exist_ok=True)
        for k in self.list(prefix):
            self.local_path(k)  # materialize each object into the cache
        return base


# --------------------------------------------------------------------------- #
#  Factory (cached per backend selection)
# --------------------------------------------------------------------------- #
_store: BlobStore | None = None
_store_backend: str | None = None


def backend_name() -> str:
    return (os.getenv("OCD_BLOB_BACKEND") or "local").strip().lower()


def get_blob_store() -> BlobStore:
    """The process-wide blob store, chosen by ``OCD_BLOB_BACKEND`` (default local)."""
    global _store, _store_backend
    name = backend_name()
    if _store is None or _store_backend != name:
        _store = S3BlobStore() if name in ("s3", "minio", "r2") else LocalBlobStore()
        _store_backend = name
    return _store


def reset_store() -> None:
    """Drop the cached store (tests / a runtime backend switch)."""
    global _store, _store_backend
    _store = None
    _store_backend = None
