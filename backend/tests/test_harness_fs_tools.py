from ocd_core.harness import workspace_fs as wfs


def test_read_file_numbers_lines(tmp_path):
    (tmp_path / "a.txt").write_text("first\nsecond\nthird\n")
    out = wfs.read_file(tmp_path, "a.txt")
    assert out["ok"] is True
    assert "1\tfirst" in out["content"]
    assert "3\tthird" in out["content"]


def test_read_file_offset_limit(tmp_path):
    (tmp_path / "a.txt").write_text("l1\nl2\nl3\nl4\nl5\n")
    out = wfs.read_file(tmp_path, "a.txt", offset=2, limit=2)
    assert "2\tl2" in out["content"] and "3\tl3" in out["content"]
    assert "l1" not in out["content"] and "l4" not in out["content"]


def test_read_file_missing(tmp_path):
    out = wfs.read_file(tmp_path, "nope.txt")
    assert out["ok"] is False and "not found" in out["error"].lower()


def test_read_file_outside_jail(tmp_path):
    out = wfs.read_file(tmp_path, "../x.txt")
    assert out["ok"] is False and "workspace" in out["error"].lower()
