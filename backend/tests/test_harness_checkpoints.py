# backend/tests/test_harness_checkpoints.py
from ocd_core.harness import checkpoints


def test_snapshot_and_restore_file(tmp_path, monkeypatch):
    store = tmp_path / "ckpt"
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("original\n")
    cp = checkpoints.CheckpointStore(store)

    cp.snapshot_before_edit("turn1", ws, "a.txt")   # capture original
    (ws / "a.txt").write_text("modified\n")          # simulate an edit

    assert cp.list("turn1")[0]["files"] == ["a.txt"]
    cp.restore("turn1", ws, what="files")
    assert (ws / "a.txt").read_text() == "original\n"


def test_snapshot_only_once_per_file_per_turn(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("v1\n")
    cp = checkpoints.CheckpointStore(tmp_path / "ckpt")
    cp.snapshot_before_edit("t", ws, "a.txt")
    (ws / "a.txt").write_text("v2\n")
    cp.snapshot_before_edit("t", ws, "a.txt")   # must NOT overwrite the v1 snapshot
    cp.restore("t", ws, what="files")
    assert (ws / "a.txt").read_text() == "v1\n"


def test_restore_new_file_deletes_it(tmp_path):
    # A file that did not exist at snapshot time is removed on restore.
    ws = tmp_path / "ws"
    ws.mkdir()
    cp = checkpoints.CheckpointStore(tmp_path / "ckpt")
    cp.snapshot_before_edit("t", ws, "new.txt")   # file absent -> tombstone
    (ws / "new.txt").write_text("created\n")
    cp.restore("t", ws, what="files")
    assert not (ws / "new.txt").exists()


def test_list_empty_turn(tmp_path):
    cp = checkpoints.CheckpointStore(tmp_path / "ckpt")
    assert cp.list("unknown") == []


def test_restore_is_fault_tolerant(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("a-orig\n")
    (ws / "b.txt").write_text("b-orig\n")
    cp = checkpoints.CheckpointStore(tmp_path / "ckpt")
    cp.snapshot_before_edit("t", ws, "a.txt")
    cp.snapshot_before_edit("t", ws, "b.txt")
    (ws / "a.txt").write_text("a-changed\n")
    (ws / "b.txt").write_text("b-changed\n")
    d = cp._ckpt_dir("t")
    next(p for p in d.iterdir() if p.suffix == ".blob").unlink()   # corrupt ONE blob
    n = cp.restore("t", ws, what="files")   # must not raise
    assert n >= 1   # the surviving entry restored


def test_list_unknown_creates_no_dir(tmp_path):
    cp = checkpoints.CheckpointStore(tmp_path / "ckpt")
    assert cp.list("never") == []
    assert not (tmp_path / "ckpt" / "never").exists()


def test_malformed_manifest_does_not_crash(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    cp = checkpoints.CheckpointStore(tmp_path / "ckpt")
    d = tmp_path / "ckpt" / "t"
    d.mkdir(parents=True)
    (d / "manifest.json").write_text("[1, 2, 3]")   # valid JSON, wrong shape
    assert cp.list("t") == []
    assert cp.restore("t", ws, what="files") == 0


def test_checkpoint_id_with_separators_stays_in_store(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("x\n")
    cp = checkpoints.CheckpointStore(tmp_path / "ckpt")
    cp.snapshot_before_edit("../evil", ws, "a.txt")
    assert not (tmp_path / "evil").exists()   # no dir created outside the store root


def test_checkpoint_id_dotdot_alone_is_neutralized(tmp_path):
    # Path("..").name == ".." (unlike "../evil" -> "evil"), so a bare ".." checkpoint_id
    # is NOT reduced by a plain Path(id).name sanitizer -- verified empirically against
    # this Python's pathlib. self.root / ".." is the store root's PARENT directory, so an
    # unguarded sanitizer would let snapshot_before_edit write manifest.json/blobs there.
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "a.txt").write_text("x\n")
    cp = checkpoints.CheckpointStore(tmp_path / "ckpt")
    cp.snapshot_before_edit("..", ws, "a.txt")
    assert not (tmp_path / "manifest.json").exists()   # nothing escaped to ckpt's parent
    assert not (tmp_path / "0.blob").exists()
    assert cp.list("..")[0]["files"] == ["a.txt"]   # consistently bucketed, still round-trips


def test_owned_by_true_for_owner_false_for_other_workspace(tmp_path):
    ws_a = tmp_path / "ws_a"
    ws_a.mkdir()
    ws_b = tmp_path / "ws_b"
    ws_b.mkdir()
    (ws_a / "a.txt").write_text("x\n")
    cp = checkpoints.CheckpointStore(tmp_path / "ckpt")
    cp.snapshot_before_edit("t", ws_a, "a.txt")   # stamps the manifest with ws_a's root
    assert cp.owned_by("t", ws_a) is True
    assert cp.owned_by("t", ws_b) is False


def test_owned_by_fails_closed_for_nonexistent_and_unstamped_manifests(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    cp = checkpoints.CheckpointStore(tmp_path / "ckpt")
    # No manifest at all yet.
    assert cp.owned_by("never-created", ws) is False
    # A legacy manifest that has files but predates the "workspace" stamp.
    d = cp._ckpt_dir("legacy")
    d.mkdir(parents=True)
    (d / "manifest.json").write_text('{"files": {"a.txt": {"blob": null, "existed": false}}}')
    assert cp.owned_by("legacy", ws) is False


def test_restore_refuses_a_checkpoint_owned_by_a_different_workspace(tmp_path):
    ws_a = tmp_path / "ws_a"
    ws_a.mkdir()
    ws_b = tmp_path / "ws_b"
    ws_b.mkdir()
    (ws_a / "shared.txt").write_text("A-orig\n")
    (ws_b / "shared.txt").write_text("B-orig\n")
    cp = checkpoints.CheckpointStore(tmp_path / "ckpt")
    cp.snapshot_before_edit("t", ws_a, "shared.txt")
    (ws_a / "shared.txt").write_text("A-changed\n")

    n = cp.restore("t", ws_b, what="files")   # B must not receive A's checkpoint
    assert n == 0
    assert (ws_b / "shared.txt").read_text() == "B-orig\n"

    n = cp.restore("t", ws_a, what="files")   # A can restore its own
    assert n == 1
    assert (ws_a / "shared.txt").read_text() == "A-orig\n"
