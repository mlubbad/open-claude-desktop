from ocd_core import projects


def test_create_get_list_card_shape(db):
    meta = projects.create_project("My Cool Project", "Build a cool thing")
    # Rich card metadata (Claude-Desktop projects grid): name/description/pinned/archived
    # + created/updated timestamps and a relative "updated" string.
    assert meta["id"] == "my-cool-project" and meta["name"] == "My Cool Project"
    assert meta["description"] == "Build a cool thing"
    assert meta["pinned"] is False and meta["archived"] is False
    assert isinstance(meta["created_at"], str) and "T" in meta["created_at"]  # ISO string
    assert isinstance(meta["updated_rel"], str)
    assert projects.get_project("my-cool-project")["name"] == "My Cool Project"
    assert [p["id"] for p in projects.list_projects()] == ["my-cool-project"]


def test_update_details_pin_archive(db):
    projects.create_project("Proj", "old desc")
    # Edit details (name + description) — only sent fields change.
    projects.update_project("proj", name="Proj Renamed", description="new desc")
    p = projects.get_project("proj")
    assert p["name"] == "Proj Renamed" and p["description"] == "new desc"
    # Pin toggles independently of the other fields.
    projects.update_project("proj", pinned=True)
    p = projects.get_project("proj")
    assert p["pinned"] is True and p["name"] == "Proj Renamed"  # name untouched
    # Unknown project -> None.
    assert projects.update_project("nope", pinned=True) is None


def test_archived_excluded_from_default_list(db):
    projects.create_project("Keep")
    projects.create_project("Gone")
    projects.update_project("gone", archived=True)
    assert [p["id"] for p in projects.list_projects()] == ["keep"]
    ids = {p["id"] for p in projects.list_projects(include_archived=True)}
    assert ids == {"keep", "gone"}


def test_list_sorted_by_updated_desc(db):
    projects.create_project("First")
    projects.create_project("Second")
    # Touching "first" makes it the most-recently-updated -> sorts to the front.
    projects.update_project("first", description="touched")
    assert [p["id"] for p in projects.list_projects()][0] == "first"


def test_duplicate_name_gets_unique_id(db):
    a = projects.create_project("Dup")
    b = projects.create_project("Dup")
    assert a["id"] == "dup" and b["id"] != a["id"] and b["id"].startswith("dup-")


def test_instructions_memory_allowlist_roundtrip(db):
    projects.create_project("P")
    assert projects.get_project_instructions("p").startswith("# Instructions for P")
    projects.save_project_instructions("p", "do X")
    assert projects.get_project_instructions("p") == "do X"
    projects.save_project_memory("p", "remember Y")
    text, rel = projects.get_project_memory("p")
    assert text == "remember Y" and isinstance(rel, str)
    assert projects.get_project_allowlist("p") == []


def test_delete_removes_row(db):
    projects.create_project("Temp")
    assert projects.delete_project("temp") is True
    assert projects.get_project("temp") is None
    assert projects.delete_project("temp") is False


def test_card_view_capacity_and_knowledge_dir(db):
    from ocd_core import config
    meta = projects.create_project("Alpha")
    assert (config.PROJECTS_DIR / "alpha" / "knowledge").is_dir()  # disk dir for uploads
    card = projects.project_card_view(meta)
    assert card["id"] == "alpha" and card["href"] == "/project/alpha"
    cap = projects.project_capacity("alpha")
    assert set(cap) == {"used_mb", "max_mb", "percent"} and cap["used_mb"] == 0.0


def test_project_persists_to_db(db):
    projects.create_project("Persisted")
    from ocd_core.db.engine import session
    from ocd_core.db.models import Project
    with session() as s:
        row = s.get(Project, "persisted")
        assert row is not None and row.name == "Persisted"
