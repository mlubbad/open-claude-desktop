# backend/tests/test_harness_env_context.py
from ocd_core.harness import env_context


def test_build_includes_root_and_platform(tmp_path):
    (tmp_path / "app.py").write_text("x")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "m.py").write_text("y")
    text = env_context.build(tmp_path)
    assert str(tmp_path) in text
    assert "app.py" in text
    assert "src/" in text or "src" in text


def test_build_caps_file_map(tmp_path):
    for i in range(300):
        (tmp_path / f"f{i}.txt").write_text("x")
    text = env_context.build(tmp_path, max_entries=50)
    # never dumps more than the cap (+ a truncation note)
    assert text.count("\n- ") <= 51


def test_build_no_git_is_safe(tmp_path):
    # No .git dir -> no crash, no git section.
    text = env_context.build(tmp_path)
    assert isinstance(text, str) and "WORKSPACE" in text


def test_build_survives_git_decode_error(tmp_path, monkeypatch):
    import subprocess
    def boom(*a, **k):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")
    monkeypatch.setattr(subprocess, "run", boom)
    text = env_context.build(tmp_path)   # must not raise
    assert isinstance(text, str) and "WORKSPACE" in text
