"""Tests for the shared atomic JSON-registry helper (ocd_core.jsonstore)."""
from ocd_core import jsonstore


def test_roundtrip_list_and_dict(tmp_path):
    lp = tmp_path / "list.json"
    jsonstore.save_json(lp, [{"a": 1}, {"b": 2}])
    assert jsonstore.load_json(lp, []) == [{"a": 1}, {"b": 2}]
    dp = tmp_path / "sub" / "dict.json"  # parent dir auto-created
    jsonstore.save_json(dp, {"k": "v"})
    assert jsonstore.load_json(dp, {}) == {"k": "v"}


def test_missing_file_returns_default(tmp_path):
    assert jsonstore.load_json(tmp_path / "nope.json", []) == []
    assert jsonstore.load_json(tmp_path / "nope.json", {}) == {}


def test_bad_json_returns_default(tmp_path):
    p = tmp_path / "corrupt.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert jsonstore.load_json(p, []) == []


def test_shape_guard_rejects_wrong_toplevel_type(tmp_path):
    # A dict on disk when the caller expects a list (and vice-versa) -> default.
    p = tmp_path / "shape.json"
    p.write_text('{"a": 1}', encoding="utf-8")
    assert jsonstore.load_json(p, []) == []
    p.write_text("[1, 2, 3]", encoding="utf-8")
    assert jsonstore.load_json(p, {}) == {}


def test_write_is_atomic_no_tmp_left_behind(tmp_path):
    p = tmp_path / "reg.json"
    jsonstore.save_json(p, [1, 2, 3])
    # The temp file used for the atomic replace must not survive a successful write.
    assert not (tmp_path / "reg.json.tmp").exists()
    assert p.exists()


def test_preserves_unicode(tmp_path):
    p = tmp_path / "u.json"
    jsonstore.save_json(p, {"name": "café ☕"})
    assert jsonstore.load_json(p, {}) == {"name": "café ☕"}
