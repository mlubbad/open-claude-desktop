from ocd_core import commands


def test_parse_known_commands():
    assert commands.parse("/projects").name == "projects"
    p = commands.parse("/project Al Jazeera")
    assert p.name == "project" and p.arg == "Al Jazeera"
    assert commands.parse("/set-instructions do X").name == "set_instructions"
    assert commands.parse("/skills").name == "skills"
    assert commands.parse("/reload-skills").name == "reload_skills"
    assert commands.parse("/refresh-catalog").name == "refresh_catalog"
    assert commands.parse("/rebuild-catalog").name == "refresh_catalog"  # alias
    assert commands.parse("/learn-finding the thing").name == "learn_finding"
    assert commands.parse("/lint-knowledge").name == "lint_knowledge"


def test_plain_message_is_not_a_command():
    p = commands.parse("how many users last week?")
    assert p.name is None and p.arg == "how many users last week?"


def test_resolve_explicit_skill_strips_prefix(tmp_path):
    (tmp_path / "hero.md").write_text(
        "name: hero\nauto: true\ntriggers: hero\n\nHero help", encoding="utf-8")
    goal, skill, via_auto = commands.resolve_skill("/hero break it down", skills_dir=tmp_path)
    assert skill == "hero" and via_auto is False and goal == "break it down"


def test_resolve_explicit_skill_no_arg_gets_default_goal(tmp_path):
    (tmp_path / "hero.md").write_text("name: hero\nauto: true\ntriggers: hero\n\nx", encoding="utf-8")
    goal, skill, via_auto = commands.resolve_skill("/hero", skills_dir=tmp_path)
    assert skill == "hero" and goal == "Run the hero skill."


def test_resolve_auto_trigger(tmp_path):
    (tmp_path / "hero.md").write_text("name: hero\nauto: true\ntriggers: hero\n\nx", encoding="utf-8")
    goal, skill, via_auto = commands.resolve_skill("show the hero rail", skills_dir=tmp_path)
    assert skill == "hero" and via_auto is True and goal == "show the hero rail"
