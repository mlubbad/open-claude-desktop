"""Tests for ocd_core.conversations — per-project conversation/thread CRUD.

No LLM is exercised: create_conversation uses _conv_title_from (a text
truncation), not the model. generate_conversation_title (LLM) is import-smoked
only.
"""
import importlib


def _reload(tmp_path, monkeypatch):
    monkeypatch.setenv("AJ360_DATA_DIR", str(tmp_path))
    cfg = importlib.reload(importlib.import_module("ocd_core.config"))
    conv = importlib.reload(importlib.import_module("ocd_core.conversations"))
    return cfg, conv


def test_conv_title_from_truncates_long_and_collapses_ws():
    import importlib
    conv = importlib.import_module("ocd_core.conversations")
    assert conv._conv_title_from("  hello   world  ") == "hello world"
    assert conv._conv_title_from("") == "New conversation"
    long = "x" * 100
    title = conv._conv_title_from(long)
    assert title.endswith("…") and len(title) == 49  # 48 chars + ellipsis


def test_create_and_get_conversation(tmp_path, monkeypatch):
    _cfg, conv = _reload(tmp_path, monkeypatch)
    c = conv.create_conversation("proj1", "What is the revenue?")
    assert c["title"] == "What is the revenue?"
    assert len(c["id"]) == 12
    assert c["messages"] == [
        {"role": "user", "content": "What is the revenue?", "kind": "user"}]
    assert c["created_at"] == c["updated_at"]

    fetched = conv.get_conversation("proj1", c["id"])
    assert fetched == c
    assert conv.get_conversation("proj1", "missing") is None


def test_save_conversation_updates_messages_and_title(tmp_path, monkeypatch):
    _cfg, conv = _reload(tmp_path, monkeypatch)
    c = conv.create_conversation("proj1", "first")
    msgs = [
        {"role": "user", "content": "first", "kind": "user"},
        {"role": "assistant", "content": "answer", "kind": "assistant"},
    ]
    saved = conv.save_conversation("proj1", c["id"], msgs, title="Renamed")
    assert saved["title"] == "Renamed"
    assert saved["messages"] == msgs
    reloaded = conv.get_conversation("proj1", c["id"])
    assert reloaded["messages"] == msgs and reloaded["title"] == "Renamed"


def test_set_pinned_and_list_conversations(tmp_path, monkeypatch):
    _cfg, conv = _reload(tmp_path, monkeypatch)
    c1 = conv.create_conversation("proj1", "alpha")
    c2 = conv.create_conversation("proj1", "beta")
    conv.set_conversation_pinned("proj1", c2["id"], True)

    listed = conv.list_conversations("proj1")
    assert len(listed) == 2
    # pinned conversation sorts first.
    assert listed[0]["id"] == c2["id"]
    assert listed[0]["pinned"] is True
    ids = {x["id"] for x in listed}
    assert ids == {c1["id"], c2["id"]}
    # summary shape
    assert listed[0]["href"] == f"/project/proj1/c/{c2['id']}"


def test_generate_conversation_title_is_importable(tmp_path, monkeypatch):
    # Import-smoke only: do not call the LLM in tests.
    _cfg, conv = _reload(tmp_path, monkeypatch)
    assert callable(conv.generate_conversation_title)
    assert callable(conv.migrate_legacy_chat_history)
