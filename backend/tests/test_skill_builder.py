"""`/skill-builder` — authoring a skill in chat and persisting it.

The gap this closes: the model could already emit a skill-shaped document via
`create_artifact`, but an artifact is not a skill — there was no tool that wrote one
into SKILLS_DIR, so "build me a skill" produced something the user could only
download. These tests pin the round trip: command → tool → file → loadable skill.
"""
import asyncio

import pytest
from ocd_core import agent, commands, config, skill_tools, skills


@pytest.fixture
def skills_dir(tmp_path, monkeypatch):
    d = tmp_path / "skills"
    d.mkdir()
    monkeypatch.setattr(config, "SKILLS_DIR", d)
    return d


ARGS = {
    "name": "curation-delta",
    "description": "Report newly added hero slides vs. the previous day.",
    "instructions": "# Curation delta\n\nRun the delta query, then report it.",
    "triggers": ["curation delta", "newly added hero"],
}


# --------------------------------------------------------------------------- #
#  Command parsing
# --------------------------------------------------------------------------- #
def test_slash_command_parses_with_and_without_an_argument():
    c = commands.parse("/skill-builder make a daily curation skill")
    assert c.name == "skill_builder"
    assert c.arg == "make a daily curation skill"
    assert commands.parse("/skill-builder").name == "skill_builder"
    assert commands.parse("/skill-builder").arg == ""


def test_plain_message_is_not_a_skill_builder_command():
    assert commands.parse("build me a skill for curation").name is None


# --------------------------------------------------------------------------- #
#  Markdown generation — must round-trip through the loader
# --------------------------------------------------------------------------- #
def test_generated_markdown_round_trips_through_the_loader(skills_dir):
    assert skill_tools.save(ARGS)["ok"] is True
    s = skills.list_skills(skills_dir)[0]
    assert s["name"] == "curation-delta"
    assert s["description"] == ARGS["description"]
    assert s["triggers"] == ["curation delta", "newly added hero"]
    assert s["auto"] is True
    assert s["instructions"] == ARGS["instructions"]


def test_no_triggers_means_no_auto_firing(skills_dir):
    skill_tools.save({**ARGS, "triggers": []})
    s = skills.list_skills(skills_dir)[0]
    assert s["auto"] is False and s["triggers"] == []
    # …but it is still reachable on demand as a slash command.
    assert commands.resolve_skill("/curation-delta", skills_dir)[1] == "curation-delta"


def test_frontmatter_stays_single_line_and_comma_safe(skills_dir):
    """`name`/`description` are newline-delimited and `triggers` is comma-split by the
    loader, so a stray newline or comma from the model would corrupt every field
    after it."""
    skill_tools.save({
        "name": "weird",
        "description": "line one\nline two: still the description",
        "instructions": "Body.",
        "triggers": ["a, b", "c\nd"],
    })
    s = skills.list_skills(skills_dir)[0]
    assert "\n" not in s["description"]
    assert s["description"].startswith("line one")
    assert s["triggers"] == ["a b", "c d"]
    assert s["instructions"] == "Body."


def test_name_is_slugified_into_a_usable_slash_command(skills_dir):
    skill_tools.save({**ARGS, "name": "AJ360 Curation Delta!"})
    s = skills.list_skills(skills_dir)[0]
    assert s["name"] == "aj360-curation-delta"
    assert commands.resolve_skill("/aj360-curation-delta 2026-07-22", skills_dir) == (
        "2026-07-22", "aj360-curation-delta", False)


def test_body_fences_are_preserved(skills_dir):
    """A skill body legitimately contains fenced SQL; only a fence wrapping the WHOLE
    payload is stripped."""
    body = "Run this:\n\n```sql\nSELECT 1;\n```"
    skill_tools.save({**ARGS, "instructions": body})
    assert skills.list_skills(skills_dir)[0]["instructions"] == body


def test_whole_body_fence_is_unwrapped(skills_dir):
    skill_tools.save({**ARGS, "instructions": "```markdown\nJust the body.\n```"})
    assert skills.list_skills(skills_dir)[0]["instructions"] == "Just the body."


# --------------------------------------------------------------------------- #
#  Validation
# --------------------------------------------------------------------------- #
def test_empty_body_is_refused(skills_dir):
    res = skill_tools.save({**ARGS, "instructions": "   "})
    assert res["ok"] is False and "instructions" in res["detail"]
    assert skills.list_skills(skills_dir) == []


def test_missing_name_is_refused(skills_dir):
    assert skill_tools.save({**ARGS, "name": "  "})["ok"] is False
    assert skills.list_skills(skills_dir) == []


# --------------------------------------------------------------------------- #
#  Idempotence + not clobbering bundled skills
# --------------------------------------------------------------------------- #
def test_resaving_the_same_name_overwrites_instead_of_duplicating(skills_dir):
    """Iterating on a skill in chat must not leave N files that shadow each other in
    resolve_skill (which returns the FIRST match in filename order)."""
    skill_tools.save(ARGS)
    skill_tools.save({**ARGS, "instructions": "Second version."})
    listed = skills.list_skills(skills_dir)
    assert len(listed) == 1
    assert listed[0]["instructions"] == "Second version."
    assert len(list(skills_dir.glob("*.md"))) == 1


def test_refuses_to_overwrite_a_skill_it_did_not_write(skills_dir):
    (skills_dir / "curation-delta.md").write_text(
        "name: curation-delta\ndescription: bundled\n\nOriginal body.",
        encoding="utf-8")
    res = skill_tools.save(ARGS)
    assert res["ok"] is False and "already exists" in res["detail"]
    assert skills.get_skill("curation-delta", skills_dir)["instructions"] == "Original body."


def test_saved_skill_is_removable_like_any_imported_one(skills_dir):
    skill_tools.save(ARGS)
    assert skills.remove_skill("curation-delta")["ok"] is True
    assert skills.list_skills(skills_dir) == []


# --------------------------------------------------------------------------- #
#  Agent wiring
# --------------------------------------------------------------------------- #
def test_tool_dispatches_through_the_agent_loop(skills_dir):
    out = asyncio.run(agent._run_one_tool("save_skill", ARGS, "tc1", None, "", 6))
    assert out["ok"] is True
    assert "/curation-delta" in out["result"]
    assert skills.get_skill("curation-delta", skills_dir) is not None


def test_tool_failure_is_reported_to_the_model_not_raised(skills_dir):
    out = asyncio.run(
        agent._run_one_tool("save_skill", {**ARGS, "instructions": ""}, "tc1", None, "", 6))
    assert out["ok"] is False and out["result"].startswith("ERROR:")


def _capture_turn(monkeypatch, **kw):
    seen = {}

    async def fake_stream(llm, model, messages, tools, temperature, max_tokens,
                          content_scope="answer", fallback_model=None, **_kw):
        seen["tools"] = [t["function"]["name"] for t in (tools or [])]
        seen["system"] = messages[0]["content"]
        yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", fake_stream)
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)

    async def run():
        async for _ in agent.run_turn("hi", [], None, "ollama/llama3.1",
                                      effort="Low", **kw):
            pass
    asyncio.run(run())
    return seen


def test_tool_is_not_offered_unless_the_command_asked_for_it(monkeypatch):
    """A saved skill is INSTRUCTIONS that later turns obey, so the tool must never be
    ambiently available — an ordinary turn (including every unattended/scheduled run,
    which never carries this flag) must not be able to write one."""
    seen = _capture_turn(monkeypatch)
    assert "save_skill" not in seen["tools"]
    assert "SKILL BUILDER" not in seen["system"]


def test_skill_builder_turn_exposes_the_tool_and_the_authoring_brief(monkeypatch):
    seen = _capture_turn(monkeypatch, skill_builder=True)
    assert "save_skill" in seen["tools"]
    assert "SKILL BUILDER" in seen["system"]


class _FakeToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = type("F", (), {"name": name, "arguments": arguments})()

    def model_dump(self):
        return {"id": self.id, "type": "function",
                "function": {"name": self.function.name, "arguments": self.function.arguments}}


def test_end_to_end_a_model_calling_the_tool_leaves_a_usable_skill(monkeypatch, skills_dir):
    """The whole path the user actually hits: skill-builder turn → model calls
    save_skill → the skill is on disk and invocable in the NEXT chat."""
    import json
    state = {"n": 0}

    async def fake_stream(llm, model, messages, tools, temperature, max_tokens,
                          content_scope="answer", fallback_model=None, **_kw):
        state["n"] += 1
        if state["n"] == 1:
            yield {"__done__": {"content": "", "note": None,
                                "tool_calls": [_FakeToolCall("c1", "save_skill",
                                                             json.dumps(ARGS))]}}
        else:
            yield {"__done__": {"content": "Saved.", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", fake_stream)
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)
    monkeypatch.setattr(agent, "resolve_turn_client",
                        lambda model, provider=None: (object(), model, None))

    async def scenario():
        return [ev async for ev in agent.run_turn(
            "build it", [], None, "m", effort="Low", skill_builder=True)]

    asyncio.run(scenario())

    # A later, ordinary turn resolves it — both as a slash command and via a trigger.
    listed = skills.list_skills(skills_dir)
    assert [s["name"] for s in listed] == ["curation-delta"]
    assert commands.resolve_skill("/curation-delta", skills_dir)[1] == "curation-delta"
    assert commands.resolve_skill("show the curation delta", skills_dir)[1] == "curation-delta"


# --------------------------------------------------------------------------- #
#  Route wiring
# --------------------------------------------------------------------------- #
def _post_goal(monkeypatch, goal):
    from fastapi.testclient import TestClient
    from ocd_core import agent as agent_mod
    seen = {}

    async def fake_run_turn(goal_, *a, **kw):
        seen["goal"] = goal_
        seen["kw"] = kw
        yield {"type": "answer_open"}

    monkeypatch.setattr(agent_mod, "run_turn", fake_run_turn)
    from app.main import app
    TestClient(app).post("/agent/turn", json={
        "project_id": None, "goal": goal, "history": [], "model": "glm-4-plus",
        "effort": "Low", "options": {}, "enabled_plugins": [],
        "enabled_connectors": [], "enabled_mcp": []})
    return seen


def test_route_turns_the_command_into_a_skill_building_turn(monkeypatch, db, skills_dir):
    seen = _post_goal(monkeypatch, "/skill-builder a daily curation report")
    assert seen["kw"]["skill_builder"] is True
    assert "a daily curation report" in seen["goal"]
    assert seen["kw"]["skill_instructions"] == ""


def test_bare_command_falls_back_to_the_conversation(monkeypatch, db, skills_dir):
    seen = _post_goal(monkeypatch, "/skill-builder")
    assert seen["kw"]["skill_builder"] is True
    assert "conversation so far" in seen["goal"]


def test_ordinary_turns_are_untouched(monkeypatch, db, skills_dir):
    seen = _post_goal(monkeypatch, "what is the hero CTR?")
    assert seen["kw"]["skill_builder"] is False
    assert seen["goal"] == "what is the hero CTR?"


def test_command_wins_over_a_same_named_skill(monkeypatch, db, skills_dir):
    """A user could save a skill called `skill-builder`; the built-in command must
    still win rather than being shadowed by it."""
    skill_tools.save({**ARGS, "name": "skill-builder", "triggers": []})
    seen = _post_goal(monkeypatch, "/skill-builder make something")
    assert seen["kw"]["skill_builder"] is True
    assert seen["kw"]["skill_instructions"] == ""
