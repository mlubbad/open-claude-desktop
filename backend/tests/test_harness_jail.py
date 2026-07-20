def test_harness_package_imports():
    import ocd_core.harness as h
    assert h is not None


import os
import pytest
from pathlib import Path
from ocd_core.harness import workspace_fs as wfs


def test_resolves_normal_child(tmp_path):
    (tmp_path / "src").mkdir()
    p = wfs.resolve_in_workspace(tmp_path, "src/app.py")
    assert isinstance(p, Path)
    assert p == (tmp_path / "src" / "app.py").resolve()


def test_rejects_parent_traversal(tmp_path):
    with pytest.raises(wfs.JailError):
        wfs.resolve_in_workspace(tmp_path, "../secret.txt")


def test_rejects_absolute_outside(tmp_path):
    with pytest.raises(wfs.JailError):
        wfs.resolve_in_workspace(tmp_path, "C:/Windows/system32/x" if os.name == "nt" else "/etc/passwd")


def test_rejects_sibling_prefix_root(tmp_path):
    # C:\ws must not match C:\ws2 — the classic string-prefix bug.
    root = tmp_path / "ws"
    root.mkdir()
    sibling = tmp_path / "ws2"
    sibling.mkdir()
    (sibling / "f.txt").write_text("x")
    with pytest.raises(wfs.JailError):
        wfs.resolve_in_workspace(root, "../ws2/f.txt")


def test_rejects_symlink_escape(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("s")
    link = root / "escape"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this host")
    with pytest.raises(wfs.JailError):
        wfs.resolve_in_workspace(root, "escape/secret.txt")


def test_empty_path_returns_root(tmp_path):
    assert wfs.resolve_in_workspace(tmp_path, "") == tmp_path.resolve()
