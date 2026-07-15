"""Pluggable object storage (hosted-SaaS slice 4b).

LocalBlobStore is the default and a transparent filesystem pass-through (the
desktop is unchanged); S3BlobStore is the opt-in multi-node backend. Both are
exercised here — the S3 one against an in-memory fake that mimics the boto3
client surface, so no network or boto3 install is needed.
"""
import io

import pytest
from ocd_core import blobstore, tenancy
from ocd_core.blobstore import LocalBlobStore, S3BlobStore


@pytest.fixture(autouse=True)
def _reset():
    blobstore.reset_store()
    yield
    blobstore.reset_store()


# --------------------------------------------------------------------------- #
#  Local backend
# --------------------------------------------------------------------------- #
def test_local_roundtrip(tmp_path):
    s = LocalBlobStore(root=tmp_path)
    key = "projects/p1/knowledge/a.txt"
    assert s.exists(key) is False
    assert s.size(key) == -1
    s.put(key, b"hello\nworld\n")
    assert s.exists(key) is True
    assert s.get(key) == b"hello\nworld\n"
    assert s.size(key) == 12
    # local_path is the canonical file — mapped 1:1 onto the historical layout.
    assert s.local_path(key) == (tmp_path / key)
    assert s.local_path(key).read_bytes() == b"hello\nworld\n"
    assert s.delete(key) is True
    assert s.delete(key) is False  # already gone
    assert s.exists(key) is False


def test_local_list_is_files_only_and_sorted(tmp_path):
    s = LocalBlobStore(root=tmp_path)
    s.put("projects/p/knowledge/b.txt", b"1")
    s.put("projects/p/knowledge/a.txt", b"2")
    s.put("projects/p/knowledge/sub/deep.txt", b"3")  # nested — not "directly under"
    keys = s.list("projects/p/knowledge")
    assert keys == ["projects/p/knowledge/a.txt", "projects/p/knowledge/b.txt"]
    assert s.list("projects/nope/knowledge") == []


def test_local_rejects_key_escaping_root(tmp_path):
    s = LocalBlobStore(root=tmp_path)
    # A ".." that would climb out of the storage root is refused outright.
    for bad in ("../evil", "projects/../../etc/passwd"):
        with pytest.raises(ValueError):
            s.put(bad, b"x")
    # A leading "/" is neutralized to a relative key (stays inside the root), never
    # writing to an absolute host path.
    s.put("/abs/path", b"x")
    assert (tmp_path / "abs/path").is_file()


# --------------------------------------------------------------------------- #
#  Workspace namespacing (defense in depth)
# --------------------------------------------------------------------------- #
def test_flag_off_keys_are_unprefixed(tmp_path):
    # No enforcement → historical, unscoped path (single-user data keeps its place).
    s = LocalBlobStore(root=tmp_path)
    s.put("projects/p/knowledge/x.txt", b"v")
    assert (tmp_path / "projects/p/knowledge/x.txt").is_file()


def test_workspaces_are_isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    s = LocalBlobStore(root=tmp_path)
    with tenancy.use_workspace("wsA"):
        s.put("projects/p/knowledge/x.txt", b"A")
    with tenancy.use_workspace("wsB"):
        s.put("projects/p/knowledge/x.txt", b"B")
        assert s.get("projects/p/knowledge/x.txt") == b"B"
        assert s.list("projects/p/knowledge") == ["projects/p/knowledge/x.txt"]
    with tenancy.use_workspace("wsA"):
        # Same logical key, different bytes — the two tenants never collide.
        assert s.get("projects/p/knowledge/x.txt") == b"A"
    # The local workspace keeps the unprefixed (legacy) path.
    with tenancy.use_workspace(tenancy.LOCAL_WORKSPACE):
        assert s.exists("projects/p/knowledge/x.txt") is False


# --------------------------------------------------------------------------- #
#  Factory
# --------------------------------------------------------------------------- #
def test_factory_defaults_to_local(monkeypatch):
    monkeypatch.delenv("OCD_BLOB_BACKEND", raising=False)
    assert blobstore.backend_name() == "local"
    assert isinstance(blobstore.get_blob_store(), LocalBlobStore)


def test_factory_s3_requires_bucket(monkeypatch):
    monkeypatch.setenv("OCD_BLOB_BACKEND", "s3")
    monkeypatch.delenv("OCD_S3_BUCKET", raising=False)
    with pytest.raises(RuntimeError):
        blobstore.get_blob_store()


# --------------------------------------------------------------------------- #
#  S3 backend — against an in-memory fake boto3 client
# --------------------------------------------------------------------------- #
class _FakeS3:
    """Just enough of the boto3 S3 client for S3BlobStore."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        return {"Body": io.BytesIO(self.objects[Key])}

    def delete_object(self, Bucket, Key):
        self.objects.pop(Key, None)

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            raise KeyError(Key)
        return {"ContentLength": len(self.objects[Key])}

    def list_objects_v2(self, Bucket, Prefix, Delimiter=None, ContinuationToken=None):
        contents = []
        for k, v in self.objects.items():
            if not k.startswith(Prefix):
                continue
            if Delimiter and Delimiter in k[len(Prefix):]:
                continue  # emulate the delimiter: skip nested keys
            contents.append({"Key": k, "Size": len(v)})
        return {"Contents": contents, "IsTruncated": False}


def _s3(tmp_path, prefix=""):
    return S3BlobStore(bucket="b", prefix=prefix, cache_root=tmp_path / "cache",
                       client=_FakeS3())


def test_s3_roundtrip_and_cache(tmp_path):
    s = _s3(tmp_path)
    key = "projects/p/knowledge/a.csv"
    assert s.exists(key) is False and s.size(key) == -1
    s.put(key, b"col\n1\n")
    assert s.exists(key) is True
    assert s.get(key) == b"col\n1\n"
    assert s.size(key) == 6
    # local_path materializes a real cache file the extractors can read.
    p = s.local_path(key)
    assert p.is_file() and p.read_bytes() == b"col\n1\n"
    assert s.delete(key) is True
    assert s.exists(key) is False
    assert not p.exists()  # cache copy purged on delete


def test_s3_list_strips_prefix_and_skips_nested(tmp_path):
    s = _s3(tmp_path, prefix="tenant")  # a shared-bucket key prefix
    s.put("projects/p/knowledge/a.txt", b"1")
    s.put("projects/p/knowledge/b.txt", b"2")
    s.put("projects/p/knowledge/sub/deep.txt", b"3")
    keys = s.list("projects/p/knowledge")
    # Logical keys come back WITHOUT the bucket prefix; nested keys are excluded.
    assert keys == ["projects/p/knowledge/a.txt", "projects/p/knowledge/b.txt"]


def test_s3_local_dir_materializes_every_file(tmp_path):
    s = _s3(tmp_path)
    s.put("projects/p/knowledge/a.txt", b"A")
    s.put("projects/p/knowledge/b.txt", b"B")
    d = s.local_dir("projects/p/knowledge")
    assert (d / "a.txt").read_bytes() == b"A"
    assert (d / "b.txt").read_bytes() == b"B"


def test_s3_is_not_local():
    assert LocalBlobStore.is_local is True
    assert S3BlobStore.is_local is False


# --------------------------------------------------------------------------- #
#  The knowledge upload API is backend-agnostic (proves the rewire)
# --------------------------------------------------------------------------- #
def test_knowledge_module_works_over_the_s3_backend(monkeypatch, tmp_path):
    """save → list → delete goes entirely through the store, so it behaves the same
    whether the backend is the local filesystem or S3 (here, the in-memory fake)."""
    from ocd_core import knowledge
    store = _s3(tmp_path)
    monkeypatch.setattr(blobstore, "get_blob_store", lambda: store)

    dest = knowledge.save_uploaded_file("proj", "notes.txt", b"line1\nline2\n")
    assert dest.is_file()  # a real (cache) path the ingest step can read
    names = [f["name"] for f in knowledge.list_project_files("proj")]
    assert names == ["notes.txt"]
    assert knowledge.delete_project_file("proj", "notes.txt") is True
    assert knowledge.list_project_files("proj") == []
    # A traversal name can't escape the project prefix (reduced to a basename).
    knowledge.save_uploaded_file("proj", "../escape.txt", b"x")
    assert [f["name"] for f in knowledge.list_project_files("proj")] == ["escape.txt"]
