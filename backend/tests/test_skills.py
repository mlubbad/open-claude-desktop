"""Tests for the canonical skill loader/matcher (ocd_core.skills).

Encodes the behavior merged from the two pre-refactor originals:
  - aj360_app/aj360_app/integrations.py  (bare-frontmatter parsing, dict API)
  - root app.py  (fenced `---` frontmatter, file_triggers, references)
The originals are the source of truth; where the task skeleton disagreed with
them, these assertions follow the originals (see notes below).
"""
from ocd_core import skills


def test_split_frontmatter_fenced():
    front, body = skills.split_frontmatter("---\nname: x\nauto: true\n---\nBODY")
    assert "name: x" in front and body == "BODY"


def test_split_frontmatter_bare():
    front, body = skills.split_frontmatter(
        "name: hero\ntriggers: hero\n# Heading\ntext")
    assert any(ln.startswith("name:") for ln in front)
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
