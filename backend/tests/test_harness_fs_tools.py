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


def test_write_new_file_no_read_required(tmp_path):
    seen = set()
    out = wfs.write_file(tmp_path, "new.txt", "hello\n", read_paths=seen)
    assert out["ok"] is True
    assert (tmp_path / "new.txt").read_text() == "hello\n"


def test_overwrite_requires_prior_read(tmp_path):
    (tmp_path / "e.txt").write_text("old\n")
    seen = set()
    out = wfs.write_file(tmp_path, "e.txt", "new\n", read_paths=seen)
    assert out["ok"] is False and "read" in out["error"].lower()


def test_overwrite_after_read_succeeds(tmp_path):
    (tmp_path / "e.txt").write_text("old\n")
    seen = set()
    wfs.read_file(tmp_path, "e.txt")
    seen.add(wfs.canonical_key(tmp_path, "e.txt"))
    out = wfs.write_file(tmp_path, "e.txt", "new\n", read_paths=seen)
    assert out["ok"] is True and (tmp_path / "e.txt").read_text() == "new\n"


def test_write_creates_parent_dirs(tmp_path):
    out = wfs.write_file(tmp_path, "a/b/c.txt", "x\n", read_paths=set())
    assert out["ok"] is True and (tmp_path / "a" / "b" / "c.txt").is_file()


def _seen(root, rel):
    return {wfs.canonical_key(root, rel)}


def test_edit_replaces_unique_string(tmp_path):
    (tmp_path / "e.py").write_text("a = 1\nb = 2\n")
    out = wfs.edit_file(tmp_path, "e.py", "b = 2", "b = 3", read_paths=_seen(tmp_path, "e.py"))
    assert out["ok"] is True
    assert (tmp_path / "e.py").read_text() == "a = 1\nb = 3\n"


def test_edit_fails_when_old_string_not_unique(tmp_path):
    (tmp_path / "e.py").write_text("x = 1\nx = 1\n")
    out = wfs.edit_file(tmp_path, "e.py", "x = 1", "x = 2", read_paths=_seen(tmp_path, "e.py"))
    assert out["ok"] is False and "unique" in out["error"].lower()
    assert (tmp_path / "e.py").read_text() == "x = 1\nx = 1\n"  # unchanged


def test_edit_replace_all(tmp_path):
    (tmp_path / "e.py").write_text("x = 1\nx = 1\n")
    out = wfs.edit_file(tmp_path, "e.py", "x = 1", "x = 2", replace_all=True,
                        read_paths=_seen(tmp_path, "e.py"))
    assert out["ok"] is True and (tmp_path / "e.py").read_text() == "x = 2\nx = 2\n"


def test_edit_fails_when_old_string_absent(tmp_path):
    (tmp_path / "e.py").write_text("a = 1\n")
    out = wfs.edit_file(tmp_path, "e.py", "zzz", "yyy", read_paths=_seen(tmp_path, "e.py"))
    assert out["ok"] is False and "not found" in out["error"].lower()


def test_edit_requires_prior_read(tmp_path):
    (tmp_path / "e.py").write_text("a = 1\n")
    out = wfs.edit_file(tmp_path, "e.py", "a = 1", "a = 2", read_paths=set())
    assert out["ok"] is False and "read" in out["error"].lower()


def test_edit_returns_unified_diff(tmp_path):
    (tmp_path / "e.py").write_text("a = 1\n")
    out = wfs.edit_file(tmp_path, "e.py", "a = 1", "a = 2", read_paths=_seen(tmp_path, "e.py"))
    assert "-a = 1" in out["diff"] and "+a = 2" in out["diff"]


def test_glob_matches_pattern(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x")
    (tmp_path / "src" / "b.py").write_text("x")
    (tmp_path / "readme.md").write_text("x")
    out = wfs.glob(tmp_path, "**/*.py")
    assert out["ok"] is True
    assert set(out["paths"]) == {"src/a.py", "src/b.py"}


def test_glob_caps_results(tmp_path):
    for i in range(10):
        (tmp_path / f"f{i}.txt").write_text("x")
    out = wfs.glob(tmp_path, "*.txt", max_results=5)
    assert len(out["paths"]) == 5 and out["truncated"] is True


def test_grep_finds_lines(tmp_path):
    (tmp_path / "a.py").write_text("import os\nx = 1\nimport sys\n")
    out = wfs.grep(tmp_path, r"^import ")
    assert out["ok"] is True
    assert any("import os" in m for m in out["matches"])
    assert any("import sys" in m for m in out["matches"])
    assert not any("x = 1" in m for m in out["matches"])


def test_grep_files_mode(tmp_path):
    (tmp_path / "a.py").write_text("TODO fix\n")
    (tmp_path / "b.py").write_text("clean\n")
    out = wfs.grep(tmp_path, "TODO", mode="files")
    assert out["files"] == ["a.py"]


def test_grep_outside_jail(tmp_path):
    out = wfs.grep(tmp_path, "x", path="../")
    assert out["ok"] is False
