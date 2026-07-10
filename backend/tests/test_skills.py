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


def test_import_skill_size_limit(tmp_path, monkeypatch):
    """A large-but-reasonable upload (over the old 256KB bulk-scan cap) is accepted;
    an absurd one is rejected with the limit in the message."""
    monkeypatch.setattr(config, "SKILLS_DIR", tmp_path)
    big = "name: big\ndescription: D\n\n" + ("x" * (500 * 1024))  # ~500 KB
    assert skills.import_skill("big.md", big)["ok"] is True
    huge = "name: huge\n\n" + ("y" * (3 * 1024 * 1024))            # ~3 MB
    res = skills.import_skill("huge.md", huge)
    assert res["ok"] is False and "MB" in res["detail"]


def test_remove_refuses_non_imported(tmp_path, monkeypatch):
    """A bundled skill (present but not in the imported manifest) can't be removed."""
    monkeypatch.setattr(config, "SKILLS_DIR", tmp_path)
    (tmp_path / "bundled.md").write_text("name: bundled\n\nBody", encoding="utf-8")
    assert skills.remove_skill("bundled")["ok"] is False
    assert (tmp_path / "bundled.md").exists()  # untouched


def test_import_skills_from_repo(tmp_path, monkeypatch):
    from ocd_core import git_sync
    monkeypatch.setattr(config, "SKILLS_DIR", tmp_path / "skills")
    repo = tmp_path / "repo"
    (repo / "skills").mkdir(parents=True)
    (repo / "skills" / "a.md").write_text("name: alpha\ndescription: A\n\nDo A", encoding="utf-8")
    (repo / "README.md").write_text("# just a readme, no frontmatter", encoding="utf-8")

    def fake_clone(url, ref, dest):
        shutil.copytree(repo, dest)
    monkeypatch.setattr(git_sync, "clone_repo", fake_clone)
    monkeypatch.setattr(config, "MARKETPLACE_ALLOW_REMOTE", True)

    res = skills.import_skills_from_repo("https://example.com/acme/skills.git")
    assert res["ok"] is True and res["count"] == 1  # README skipped, alpha imported
    assert any(s["name"] == "alpha" for s in skills.list_skills())


def test_import_skills_from_repo_rejects_bad_url(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SKILLS_DIR", tmp_path)
    assert skills.import_skills_from_repo("file:///etc")["ok"] is False


def _make_zip(path, entries):
    import zipfile
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return path


def test_import_skills_from_zip_canonical_folder(tmp_path, monkeypatch):
    """A zipped skill folder (SKILL.md + references/) imports one clean skill —
    the exact case from the report: 'it must be extracted'."""
    monkeypatch.setattr(config, "SKILLS_DIR", tmp_path / "skills")
    z = _make_zip(tmp_path / "bundle.zip", {
        "ab-testing/SKILL.md": "---\nname: ab-testing\ndescription: AB\n---\nRun clean tests.",
        "ab-testing/references/guide.md": "name: guide\n\nreference material",
        "ad-creative/SKILL.md": "no frontmatter — body of the ad-creative skill.",
    })
    res = skills.import_skills_from_zip(z, "bundle.zip")
    assert res["ok"] is True
    assert set(res["names"]) == {"ab-testing", "ad-creative"}  # references/ ignored
    assert "guide" not in {s["name"] for s in skills.list_skills()}


def test_import_skills_from_zip_root_level_skill_md(tmp_path, monkeypatch):
    """A zip whose root IS the skill folder falls back to the zip's own name."""
    monkeypatch.setattr(config, "SKILLS_DIR", tmp_path / "skills")
    z = _make_zip(tmp_path / "seo-audit.zip", {
        "SKILL.md": "Body of the skill — no frontmatter name.",
        "references/notes.md": "name: notes\n\nnotes",
    })
    res = skills.import_skills_from_zip(z, "seo-audit.zip")
    assert res["ok"] is True and res["names"] == ["seo-audit"]


def test_import_skills_from_zip_rejects_traversal_and_junk(tmp_path, monkeypatch):
    """Zip-slip entries are skipped; a zip with no skills is rejected; non-zip too."""
    monkeypatch.setattr(config, "SKILLS_DIR", tmp_path / "skills")
    evil = _make_zip(tmp_path / "evil.zip", {
        "../outside/SKILL.md": "escapes the extraction dir",
        "readme.txt": "nothing here",
    })
    res = skills.import_skills_from_zip(evil, "evil.zip")
    assert res["ok"] is False  # traversal entry skipped -> no skills found
    assert not (tmp_path / "outside").exists()  # nothing escaped the jail
    notzip = tmp_path / "x.zip"
    notzip.write_text("plain text, not an archive", encoding="utf-8")
    assert skills.import_skills_from_zip(notzip, "x.zip")["ok"] is False


def test_import_skills_canonical_skill_md_layout(tmp_path, monkeypatch):
    """A repo using skills/<name>/SKILL.md imports one skill per folder — its references/
    docs are ignored, and a SKILL.md without a name falls back to its folder name."""
    from ocd_core import git_sync
    monkeypatch.setattr(config, "SKILLS_DIR", tmp_path / "skills")
    monkeypatch.setattr(config, "MARKETPLACE_ALLOW_REMOTE", True)
    repo = tmp_path / "repo"
    (repo / "skills" / "ab-testing" / "references").mkdir(parents=True)
    (repo / "skills" / "ab-testing" / "SKILL.md").write_text(
        "---\nname: ab-testing\ndescription: AB\n---\nRun clean A/B tests.", encoding="utf-8")
    (repo / "skills" / "ab-testing" / "references" / "guide.md").write_text(
        "name: guide\n\nreference material", encoding="utf-8")  # must be ignored
    (repo / "skills" / "ad-creative").mkdir(parents=True)
    (repo / "skills" / "ad-creative" / "SKILL.md").write_text(
        "no frontmatter here — just the body of the ad-creative skill.", encoding="utf-8")
    (repo / "README.md").write_text("# repo readme", encoding="utf-8")
    monkeypatch.setattr(git_sync, "clone_repo", lambda url, ref, dest: shutil.copytree(repo, dest))

    res = skills.import_skills_from_repo("https://example.com/x/marketingskills.git")
    assert res["ok"] is True
    # SKILL.md only; references/README ignored; nameless SKILL.md -> folder name.
    assert set(res["names"]) == {"ab-testing", "ad-creative"}
    assert "guide" not in {s["name"] for s in skills.list_skills()}
