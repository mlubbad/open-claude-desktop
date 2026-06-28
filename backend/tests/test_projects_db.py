import pytest
from ocd_core import projects


def test_create_get_list_lean_shape(db):
    meta = projects.create_project("My Cool Project")
    assert meta == {"id": "my-cool-project", "name": "My Cool Project",
                    "created_at": meta["created_at"]}
    assert isinstance(meta["created_at"], str) and "T" in meta["created_at"]  # ISO string
    assert projects.get_project("my-cool-project")["name"] == "My Cool Project"
    assert [p["id"] for p in projects.list_projects()] == ["my-cool-project"]


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
