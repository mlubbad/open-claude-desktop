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


def test_list_all_excludes_orphans_and_projects_columns(db):
    """One projected query across every conversation: real projects + General are
    included, a conversation whose project no longer exists is skipped, and a
    summary never carries the transcript blob."""
    from ocd_core import projects
    p = projects.create_project("Real")
    cv.create_conversation(p["id"], "in a real project")
    cv.create_conversation("general", "a general chat")
    cv.create_conversation("ghost-deleted-project", "orphaned")  # no such project

    items = cv.list_all_conversations()
    pids = {i["project_id"] for i in items}
    assert p["id"] in pids and "general" in pids
    assert "ghost-deleted-project" not in pids       # orphan excluded
    # Column-projected summaries: no transcript/messages field ever ships in a listing.
    assert all("messages" not in i and "transcript" not in i for i in items)
    assert all({"id", "title", "updated_at", "pinned", "href"} <= set(i) for i in items)


def test_list_conversations_summary_has_no_transcript(db):
    cv.create_conversation("p1", "hello")
    summaries = cv.list_conversations("p1")
    assert summaries and "messages" not in summaries[0] and "transcript" not in summaries[0]


# ---- branching --------------------------------------------------------------------

def _seed(msgs):
    conv = cv.create_conversation("p1", msgs[0]["content"])
    cv.save_conversation("p1", conv["id"], msgs)
    return conv["id"]


def test_branch_copies_history_up_to_the_fork_and_links_parent(db):
    msgs = [{"role": "user", "content": "q1", "kind": "user"},
            {"role": "assistant", "content": "a1", "kind": "blocks"},
            {"role": "user", "content": "q2", "kind": "user"},
            {"role": "assistant", "content": "a2", "kind": "blocks"}]
    src = _seed(msgs)
    branch = cv.branch_conversation("p1", src, at_index=1)  # fork right after a1
    assert branch is not None
    assert branch["id"] != src
    assert branch["parent_id"] == src and branch["fork_index"] == 1
    assert [m["content"] for m in branch["messages"]] == ["q1", "a1"]  # 0..1 inclusive
    # Editing the branch must not touch the parent (deep copy).
    cv.save_conversation("p1", branch["id"],
                         branch["messages"] + [{"role": "user", "content": "q2-alt", "kind": "user"}])
    assert [m["content"] for m in cv.get_conversation("p1", src)["messages"]] == \
        ["q1", "a1", "q2", "a2"]


def test_branch_out_of_range_or_missing_returns_none(db):
    src = _seed([{"role": "user", "content": "only", "kind": "user"}])
    assert cv.branch_conversation("p1", src, at_index=5) is None      # index past the end
    assert cv.branch_conversation("p1", src, at_index=-1) is None     # negative
    assert cv.branch_conversation("p1", "nope", at_index=0) is None   # no such conv
    assert cv.branch_conversation("other", src, at_index=0) is None   # wrong project


def test_branch_family_returns_the_whole_tree(db):
    msgs = [{"role": "user", "content": f"m{i}", "kind": "user"} for i in range(4)]
    root = _seed(msgs)
    b1 = cv.branch_conversation("p1", root, at_index=1)["id"]
    b2 = cv.branch_conversation("p1", root, at_index=2)["id"]      # sibling of b1
    gb = cv.branch_conversation("p1", b1, at_index=0)["id"]        # grandchild via b1

    fam = cv.branch_family("p1", b1)
    assert fam["root"] == root and fam["current"] == b1
    ids = {n["id"] for n in fam["nodes"]}
    assert ids == {root, b1, b2, gb}                               # full family from any node
    # Same tree is returned no matter which member you ask from.
    assert {n["id"] for n in cv.branch_family("p1", gb)["nodes"]} == ids


def test_branch_routes(db):
    from app.main import app
    from fastapi.testclient import TestClient
    c = TestClient(app)
    src = _seed([{"role": "user", "content": "a", "kind": "user"},
                 {"role": "assistant", "content": "b", "kind": "blocks"}])
    r = c.post(f"/projects/p1/conversations/{src}/branch", json={"at_index": 0})
    assert r.status_code == 200
    branch = r.json()
    assert branch["parent_id"] == src and len(branch["messages"]) == 1
    fam = c.get(f"/projects/p1/conversations/{src}/branches").json()
    assert {n["id"] for n in fam["nodes"]} == {src, branch["id"]}
    # A bad index 404s rather than 500s.
    assert c.post(f"/projects/p1/conversations/{src}/branch", json={"at_index": 99}).status_code == 404


def test_conversation_persists_to_db(db):
    conv = cv.create_conversation("p1", "hello world")
    from ocd_core.db.engine import session
    from ocd_core.db.models import Conversation
    with session() as s:
        row = s.get(Conversation, conv["id"])
        assert row is not None and row.project_id == "p1"
        assert row.transcript[0]["content"] == "hello world"
