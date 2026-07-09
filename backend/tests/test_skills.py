"""Tests for the canonical skill loader/matcher (ocd_core.skills).

Encodes the behavior merged from the two pre-refactor originals:
  - aj360_app/aj360_app/integrations.py  (bare-frontmatter parsing, dict API)
  - root app.py  (fenced `---` frontmatter, file_triggers, references)
The originals are the source of truth; where the task skeleton disagreed with
them, these assertions follow the originals (see notes below).
"""
import shutil

from ocd_core import config, skills


def test_split_frontmatter_fenced():
    front, body = skills.split_frontmatter("---\nname: x\nauto: true\n---\nBODY")
    assert "name: x" in front and body == "BODY"


def test_split_frontmatter_bare():
    front, body = skills.split_frontmatter(
        "name: hero\ntriggers: hero\n# Heading\ntext")
    assert any(line.startswith("name:") for line in front)
    assert body.startswith("# Heading")


def test_list_skills_skips_disabled(tmp_path):
    (tmp_path / "a.md").write_text(
        "name: a\nauto: true\ntriggers: foo\n\nDo A", encoding="utf-8")
    (tmp_path / "b.md").write_text(
        "name: b\ndisabled: true\n\nDo B", encoding="utf-8")
    got = skills.list_skills(tmp_path)
    names = {s["name"] for s in got}
    assert names == {"a"}


def test_matching_skill_word_boundary(tmp_path):
    (tmp_path / "hero.md").write_text(
        "name: hero\nauto: true\ntriggers: hero, carousel\n\nHero help",
        encoding="utf-8")
    assert skills.matching_skill("show the hero rail", tmp_path) == "hero"
    # boundary, not substring: 'heroic' must NOT match the trigger 'hero'
    assert skills.matching_skill("heroic effort", tmp_path) == ""


def test_matching_skill_filename_trigger(tmp_path):
    (tmp_path / "csv.md").write_text(
        "name: csv\nauto: true\nfile_triggers: .csv\n\nCSV help", encoding="utf-8")
    assert skills.matching_skill("", tmp_path, filenames=["data.csv"]) == "csv"


# --- extra assertions encoding the originals' contract (shapes / fields) --- #

def test_list_skills_returns_superset_dicts(tmp_path):
    """integrations.list_skills callers rely on {name, description, instructions,
    auto, triggers}; the merged dict is a superset that also carries
    file_triggers + references (from app.py's Skill)."""
    (tmp_path / "s.md").write_text(
        "name: s\ndescription: D\nauto: true\ntriggers: x\n"
        "file_triggers: .pdf\nreferences: r1, r2\n\nBody here",
        encoding="utf-8")
    s = skills.list_skills(tmp_path)[0]
    assert s["name"] == "s"
    assert s["description"] == "D"
    assert s["instructions"] == "Body here"
    assert s["auto"] is True
    assert s["triggers"] == ["x"]
    assert s["file_triggers"] == [".pdf"]
    assert s["references"] == ["r1", "r2"]


def test_get_skill_returns_dict_or_none(tmp_path):
    (tmp_path / "g.md").write_text("name: g\nauto: true\n\nbody", encoding="utf-8")
    assert skills.get_skill("g", tmp_path)["name"] == "g"
    assert skills.get_skill("missing", tmp_path) is None


# --------------------------- importing skills --------------------------- #

SKILL_MD = "name: greeter\ndescription: Say hi\n\nAlways greet warmly."


def test_import_skill_then_remove(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SKILLS_DIR", tmp_path)
    res = skills.import_skill("greeter.md", SKILL_MD)
    assert res["ok"] is True and res["name"] == "greeter"
    listed = skills.list_skills()
    entry = next(s for s in listed if s["name"] == "greeter")
    assert entry["imported"] is True  # flagged as user-imported
    # Remove it — the file is gone and it drops out of the list.
    assert skills.remove_skill("greeter")["ok"] is True
    assert not any(s["name"] == "greeter" for s in skills.list_skills())


def test_import_skill_rejects_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SKILLS_DIR", tmp_path)
    assert skills.import_skill("x.md", "name: x\n")["ok"] is False  # no body
    assert skills.list_skills() == []


def test_remove_refuses_non_imported(tmp_path, monkeypatch):
    """A bundled skill (present but not in the imported manifest) can't be removed."""
    monkeypatch.setattr(config, "SKILLS_DIR", tmp_path)
    (tmp_path / "bundled.md").write_text("name: bundled\n\nBody", encoding="utf-8")
    assert skills.remove_skill("bundled")["ok"] is False
    assert (tmp_path / "bundled.md").exists()  # untouched


def test_import_skills_from_repo(tmp_path, monkeypatch):
    from ocd_core import marketplace
    monkeypatch.setattr(config, "SKILLS_DIR", tmp_path / "skills")
    repo = tmp_path / "repo"
    (repo / "skills").mkdir(parents=True)
    (repo / "skills" / "a.md").write_text("name: alpha\ndescription: A\n\nDo A", encoding="utf-8")
    (repo / "README.md").write_text("# just a readme, no frontmatter", encoding="utf-8")

    def fake_clone(url, ref, dest):
        shutil.copytree(repo, dest)
    monkeypatch.setattr(marketplace, "_clone_repo", fake_clone)
    monkeypatch.setattr(config, "MARKETPLACE_ALLOW_REMOTE", True)

    res = skills.import_skills_from_repo("https://example.com/acme/skills.git")
    assert res["ok"] is True and res["count"] == 1  # README skipped, alpha imported
    assert any(s["name"] == "alpha" for s in skills.list_skills())


def test_import_skills_from_repo_rejects_bad_url(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SKILLS_DIR", tmp_path)
    assert skills.import_skills_from_repo("file:///etc")["ok"] is False
