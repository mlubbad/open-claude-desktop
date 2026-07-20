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
