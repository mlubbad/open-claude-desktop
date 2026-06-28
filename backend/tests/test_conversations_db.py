from ocd_core import conversations as cv


def test_conv_title_from_truncates_long_and_collapses_ws():
    assert cv._conv_title_from("  hello   world  ") == "hello world"
    assert cv._conv_title_from("") == "New conversation"
    long = "x" * 100
    title = cv._conv_title_from(long)
    assert title.endswith("…") and len(title) == 49  # 48 chars + ellipsis


def test_create_get_save(db):
    conv = cv.create_conversation("p1", "first message about hero rails")
    assert conv["title"].startswith("first message")
    assert conv["messages"][0] == {"role": "user", "content": "first message about hero rails", "kind": "user"}
    assert isinstance(conv["created_at"], str) and "T" in conv["created_at"]
    cv.save_conversation("p1", conv["id"], [{"role": "user", "content": "hi", "kind": "user"}], title="T")
    got = cv.get_conversation("p1", conv["id"])
    assert got["title"] == "T" and got["messages"][-1]["content"] == "hi"
    assert cv.get_conversation("other", conv["id"]) is None  # scoped to project


def test_pin_list_move_delete(db):
    conv = cv.create_conversation("p1", "msg")
    cv.set_conversation_pinned("p1", conv["id"], True)
    summaries = cv.list_conversations("p1")
    assert summaries[0]["pinned"] is True and summaries[0]["id"] == conv["id"]
    assert "updated_rel" in summaries[0] and summaries[0]["href"].endswith(conv["id"])
    assert cv.move_conversation("p1", conv["id"], "p2") is True
    assert cv.get_conversation("p1", conv["id"]) is None
    assert cv.get_conversation("p2", conv["id"]) is not None
    cv.delete_conversation("p2", conv["id"])
    assert cv.get_conversation("p2", conv["id"]) is None


def test_list_all_includes_general(db):
    cv.create_conversation("general", "a general chat")
    items = cv.list_all_conversations()
    assert any(i["project_id"] == "general" for i in items)


def test_conversation_persists_to_db(db):
    conv = cv.create_conversation("p1", "hello world")
    from ocd_core.db.engine import session
    from ocd_core.db.models import Conversation
    with session() as s:
        row = s.get(Conversation, conv["id"])
        assert row is not None and row.project_id == "p1"
        assert row.transcript[0]["content"] == "hello world"
