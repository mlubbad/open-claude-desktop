# backend/tests/test_harness_registry.py
import pytest
from ocd_core import workspace_registry as wr


def test_register_and_get(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "_STORE", tmp_path / "workspaces.json")
    (tmp_path / "proj").mkdir()
    ws = wr.register(str(tmp_path / "proj"))
    assert ws["id"]
    got = wr.get(ws["id"])
    assert got["root"] == str(tmp_path / "proj")


def test_list_recents_orders_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "_STORE", tmp_path / "workspaces.json")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    a = wr.register(str(tmp_path / "a"))
    b = wr.register(str(tmp_path / "b"))
    wr.touch(a["id"])   # a is now most-recent
    ids = [w["id"] for w in wr.list_recents()]
    assert ids[0] == a["id"] and b["id"] in ids


def test_get_unknown_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "_STORE", tmp_path / "workspaces.json")
    assert wr.get("nope") is None


def test_rules_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "_STORE", tmp_path / "workspaces.json")
    (tmp_path / "p").mkdir()
    ws = wr.register(str(tmp_path / "p"))
    wr.set_rules(ws["id"], {"allow": ["bash(git *)"], "deny": [], "ask": []})
    assert wr.get(ws["id"])["rules"]["allow"] == ["bash(git *)"]


def test_newly_registered_is_most_recent(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "_STORE", tmp_path / "workspaces.json")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "c").mkdir()
    a = wr.register(str(tmp_path / "a"))
    wr.register(str(tmp_path / "b"))
    wr.touch(a["id"])
    wr.touch(a["id"])
    c = wr.register(str(tmp_path / "c"))
    assert wr.list_recents()[0]["id"] == c["id"]


def test_register_rejects_nonexistent_root(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "_STORE", tmp_path / "workspaces.json")
    with pytest.raises(ValueError):
        wr.register(str(tmp_path / "does-not-exist"))


def test_register_rejects_a_file(tmp_path, monkeypatch):
    monkeypatch.setattr(wr, "_STORE", tmp_path / "workspaces.json")
    f = tmp_path / "notadir.txt"
    f.write_text("x")
    with pytest.raises(ValueError):
        wr.register(str(f))
