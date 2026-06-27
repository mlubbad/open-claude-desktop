"""Tests for ocd_core.projects — the project registry + metadata accessors.

The module snapshots config paths at import time (e.g. _REGISTRY_FILE =
config.PROJECTS_DIR / "_registry.json"), so each test reloads config *then*
projects after pointing AJ360_DATA_DIR at a tmp dir.
"""
import importlib


def _reload(tmp_path, monkeypatch):
    monkeypatch.setenv("AJ360_DATA_DIR", str(tmp_path))
    cfg = importlib.reload(importlib.import_module("ocd_core.config"))
    projects = importlib.reload(importlib.import_module("ocd_core.projects"))
    return cfg, projects


def test_create_get_list_roundtrip(tmp_path, monkeypatch):
    _cfg, projects = _reload(tmp_path, monkeypatch)
    assert projects.list_projects() == []

    meta = projects.create_project("My First Project")
    # Real shape: id (slug), name (verbatim), created_at (iso).
    assert meta["id"] == "my-first-project"
    assert meta["name"] == "My First Project"
    assert "created_at" in meta and meta["created_at"]

    assert projects.get_project("my-first-project") == meta
    assert projects.get_project("does-not-exist") is None
    listed = projects.list_projects()
    assert len(listed) == 1 and listed[0]["id"] == "my-first-project"


def test_create_writes_project_dir_and_instructions(tmp_path, monkeypatch):
    cfg, projects = _reload(tmp_path, monkeypatch)
    projects.create_project("Alpha")
    proj_dir = cfg.PROJECTS_DIR / "alpha"
    assert (proj_dir / "knowledge").is_dir()
    instr = proj_dir / "instructions.md"
    assert instr.exists()
    assert "Instructions for Alpha" in instr.read_text(encoding="utf-8")


def test_duplicate_name_gets_unique_id(tmp_path, monkeypatch):
    _cfg, projects = _reload(tmp_path, monkeypatch)
    a = projects.create_project("Same Name")
    b = projects.create_project("Same Name")
    assert a["id"] == "same-name"
    assert b["id"] != a["id"]
    assert b["id"].startswith("same-name-")
    assert len(projects.list_projects()) == 2


def test_delete_project_removes_dir_and_registry_entry(tmp_path, monkeypatch):
    cfg, projects = _reload(tmp_path, monkeypatch)
    projects.create_project("Doomed")
    proj_dir = cfg.PROJECTS_DIR / "doomed"
    assert proj_dir.exists()

    assert projects.delete_project("doomed") is True
    assert not proj_dir.exists()
    assert projects.get_project("doomed") is None
    # Deleting a non-existent project returns False.
    assert projects.delete_project("doomed") is False


def test_instructions_and_memory_roundtrip(tmp_path, monkeypatch):
    _cfg, projects = _reload(tmp_path, monkeypatch)
    projects.create_project("Beta")
    projects.save_project_instructions("beta", "# Custom\nrules")
    assert projects.get_project_instructions("beta") == "# Custom\nrules"

    # Empty/missing memory returns ("", "").
    assert projects.get_project_memory("beta") == ("", "")
    projects.save_project_memory("beta", "remember this")
    text, rel = projects.get_project_memory("beta")
    assert text == "remember this"
    assert rel  # non-empty relative-time string


def test_allowlist_default_empty_and_card_view(tmp_path, monkeypatch):
    _cfg, projects = _reload(tmp_path, monkeypatch)
    meta = projects.create_project("Gamma")
    assert projects.get_project_allowlist("gamma") == []

    card = projects.project_card_view(meta)
    assert card["id"] == "gamma"
    assert card["name"] == "Gamma"
    assert card["href"] == "/project/gamma"
    # capacity shape
    cap = projects.project_capacity("gamma")
    assert set(cap) == {"used_mb", "max_mb", "percent"}
    assert cap["used_mb"] == 0.0
