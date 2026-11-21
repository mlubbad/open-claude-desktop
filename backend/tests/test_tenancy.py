"""Workspace tenancy (hosted-SaaS foundation).

Two axes are pinned here:
  1. Flag OFF (the desktop default) → byte-for-byte unchanged: no filtering, new rows
     keep the historical NULL workspace_id.
  2. Flag ON → projects and conversations are isolated per workspace, legacy NULL rows
     belong to `local`, and cross-workspace mutations are denied (404 at the route).
"""
import pytest
from fastapi.testclient import TestClient
from ocd_core import conversations as cv
from ocd_core import projects as pj
from ocd_core import tenancy


@pytest.fixture
def enforced(monkeypatch):
    """Turn multi-tenant enforcement on for the duration of a test."""
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    monkeypatch.setenv("OCD_ALLOW_DEV_WORKSPACE_HEADER", "1")
    assert tenancy.enforcing() is True
    yield


# ---- flag OFF: the local desktop path is untouched -----------------------------------

def test_flag_off_is_a_noop(db):
    """Default (no OCD_MULTI_TENANT): nothing is scoped and new rows keep NULL workspace."""
    assert tenancy.enforcing() is False
    p = pj.create_project("Solo")
    assert p in pj.list_projects() or any(x["id"] == p["id"] for x in pj.list_projects())
    from ocd_core.db.engine import session
    from ocd_core.db.models import Project
    with session() as s:
        assert s.get(Project, p["id"]).workspace_id is None  # unchanged from before tenancy
    # A conversation created locally is visible with no workspace tag.
    c = cv.create_conversation("general", "hi")
    assert cv.get_conversation("general", c["id"]) is not None
    with session() as s:
        from ocd_core.db.models import Conversation
        assert s.get(Conversation, c["id"]).workspace_id is None


# ---- flag ON: project isolation ------------------------------------------------------

def test_projects_isolated_between_workspaces(db, enforced):
    with tenancy.use_workspace("wsA"):
        a = pj.create_project("Alpha")
    with tenancy.use_workspace("wsB"):
        b = pj.create_project("Beta")

    with tenancy.use_workspace("wsA"):
        ids = {p["id"] for p in pj.list_projects()}
        assert a["id"] in ids and b["id"] not in ids
        assert pj.get_project(a["id"]) is not None
        assert pj.get_project(b["id"]) is None                 # can't read across
        assert pj.update_project(b["id"], name="hijack") is None
        assert pj.delete_project(b["id"]) is False
        assert pj.get_project_instructions(b["id"]) == ""
        assert pj.get_project_memory(b["id"]) == ("", "")

    with tenancy.use_workspace("wsB"):
        ids = {p["id"] for p in pj.list_projects()}
        assert b["id"] in ids and a["id"] not in ids
        # B's write to its own project still works — scoping never blocks the owner.
        assert pj.update_project(b["id"], name="Beta II")["name"] == "Beta II"


def test_new_rows_are_stamped_when_enforcing(db, enforced):
    with tenancy.use_workspace("team-x"):
        p = pj.create_project("Tagged")
    from ocd_core.db.engine import session
    from ocd_core.db.models import Project
    with session() as s:
        row = s.get(Project, p["id"])
        assert row.workspace_id == "team-x" and row.owner_id == "team-x"


# ---- flag ON: conversation isolation, including the shared "general" project ----------

def test_conversations_isolated_even_in_general(db, enforced):
    with tenancy.use_workspace("wsA"):
        a = cv.create_conversation("general", "A's private chat")
    with tenancy.use_workspace("wsB"):
        b = cv.create_conversation("general", "B's private chat")

    with tenancy.use_workspace("wsA"):
        assert [c["id"] for c in cv.list_conversations("general")] == [a["id"]]
        assert {c["id"] for c in cv.list_all_conversations()} == {a["id"]}
        assert cv.get_conversation("general", b["id"]) is None
        # Overwriting B's conversation by id is denied (upsert can't degrade to not-found).
        with pytest.raises(tenancy.WorkspaceForbidden):
            cv.save_conversation("general", b["id"],
                                 [{"role": "user", "content": "x", "kind": "user"}])
        assert cv.branch_conversation("general", b["id"], 0) is None

    with tenancy.use_workspace("wsB"):
        assert [c["id"] for c in cv.list_conversations("general")] == [b["id"]]
        # B still fully owns its conversation.
        saved = cv.save_conversation("general", b["id"],
                                     [{"role": "user", "content": "mine", "kind": "user"}])
        assert saved["messages"][-1]["content"] == "mine"


# ---- flag ON: legacy NULL-workspace rows belong to `local` ---------------------------

def test_legacy_null_rows_resolve_to_local(db, monkeypatch):
    # Create BEFORE enforcement → workspace_id stays NULL (a pre-existing single-user DB).
    legacy_p = pj.create_project("Legacy")
    legacy_c = cv.create_conversation("general", "old chat")

    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    # The implicit `local` workspace still sees everything it had before.
    with tenancy.use_workspace(tenancy.LOCAL_WORKSPACE):
        assert pj.get_project(legacy_p["id"]) is not None
        assert cv.get_conversation("general", legacy_c["id"]) is not None
        assert legacy_p["id"] in {p["id"] for p in pj.list_projects()}
    # A brand-new workspace does NOT inherit the legacy rows.
    with tenancy.use_workspace("newcomer"):
        assert pj.get_project(legacy_p["id"]) is None
        assert cv.get_conversation("general", legacy_c["id"]) is None
        assert legacy_p["id"] not in {p["id"] for p in pj.list_projects()}


# ---- route-level: the workspace resolves from the request and scopes the call ---------

def test_routes_scope_by_workspace_header(db, enforced):
    from app.main import app
    c = TestClient(app)
    hdr_a = {"X-OCD-Workspace": "wsA"}
    hdr_b = {"X-OCD-Workspace": "wsB"}

    made = c.post("/projects/general/conversations",
                  json={"first_message": "hello from A"}, headers=hdr_a).json()
    cid = made["id"]

    # A sees it through the full request stack (proves the ContextVar reaches the handler).
    assert c.get(f"/projects/general/conversations/{cid}", headers=hdr_a).status_code == 200
    assert any(x["id"] == cid
               for x in c.get("/conversations", headers=hdr_a).json())
    # B cannot see or overwrite it.
    assert c.get(f"/projects/general/conversations/{cid}", headers=hdr_b).status_code == 404
    assert c.get("/conversations", headers=hdr_b).json() == []
    conflict = c.put(f"/projects/general/conversations/{cid}",
                     json={"messages": [{"role": "user", "content": "hijack", "kind": "user"}]},
                     headers=hdr_b)
    assert conflict.status_code == 404  # WorkspaceForbidden → not-found, no existence leak


def test_resolve_workspace_prefers_header_then_bearer(monkeypatch):
    from starlette.datastructures import Headers
    monkeypatch.setenv("OCD_MULTI_TENANT", "1")
    # No enforcement short-circuit is tested elsewhere; here enforcement is on.
    assert tenancy.resolve_workspace(Headers({"x-ocd-workspace": "explicit"})) == "explicit"
    # Falls back to `local` with no header and no valid bearer.
    assert tenancy.resolve_workspace(Headers({})) == tenancy.LOCAL_WORKSPACE


def test_resolve_workspace_is_local_when_flag_off():
    from starlette.datastructures import Headers
    # Even with a header, no enforcement means everything is the local workspace.
    assert tenancy.resolve_workspace(Headers({"x-ocd-workspace": "ignored"})) == tenancy.LOCAL_WORKSPACE
