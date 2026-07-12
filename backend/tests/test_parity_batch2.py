"""Parity batch 2: P0-5 broad file extraction, P0-6 response styles, P1-1 provider
usage + native reasoning, P1-4 search_past_chats, P1-3 connectors directory,
P1-7 skill asset import.
"""
import asyncio
import types
import zipfile

import pytest
from ocd_core import agent, knowledge, prompts, usage

# --------------------------------------------------------------------------- #
#  P0-5 — extraction: office formats via stdlib, full CSV, errors surfaced
# --------------------------------------------------------------------------- #
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_S = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def test_docx_extraction(tmp_path):
    doc = (f'<w:document xmlns:w="{_W}"><w:body>'
           '<w:p><w:r><w:t>Hello</w:t><w:t> world</w:t></w:r></w:p>'
           '<w:p><w:r><w:t>Second paragraph</w:t></w:r></w:p>'
           "</w:body></w:document>")
    f = tmp_path / "a.docx"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("word/document.xml", doc)
    assert knowledge.extract_text_from_file(f) == "Hello world\nSecond paragraph"


def test_pptx_extraction_orders_slides_numerically(tmp_path):
    def slide(text):
        return (f'<p:sld xmlns:a="{_A}" xmlns:p="x"><a:t>{text}</a:t></p:sld>')
    f = tmp_path / "deck.pptx"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("ppt/slides/slide10.xml", slide("ten"))
        z.writestr("ppt/slides/slide2.xml", slide("two"))
    out = knowledge.extract_text_from_file(f)
    assert out.index("two") < out.index("ten")  # numeric, not lexicographic
    assert "[slide 1]" in out and "[slide 2]" in out


def test_xlsx_extraction_resolves_shared_strings(tmp_path):
    shared = (f'<sst xmlns="{_S}"><si><t>name</t></si><si><t>Ada</t></si></sst>')
    sheet = (f'<worksheet xmlns="{_S}"><sheetData>'
             '<row><c t="s"><v>0</v></c><c><v>42</v></c></row>'
             '<row><c t="s"><v>1</v></c><c><v>7</v></c></row>'
             "</sheetData></worksheet>")
    f = tmp_path / "b.xlsx"
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("xl/sharedStrings.xml", shared)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    out = knowledge.extract_text_from_file(f)
    assert "name\t42" in out and "Ada\t7" in out


def test_html_extraction_skips_scripts(tmp_path):
    f = tmp_path / "page.html"
    f.write_text("<html><script>var x=1;</script><body><h1>Title</h1>"
                 "<p>Body text</p></body></html>", encoding="utf-8")
    out = knowledge.extract_text_from_file(f)
    assert "Title" in out and "Body text" in out and "var x" not in out


def test_rtf_extraction_strips_control_words(tmp_path):
    f = tmp_path / "note.rtf"
    f.write_text(r"{\rtf1\ansi\deff0 {\fonttbl{\f0 Arial;}}Hello \b bold\b0 world}",
                 encoding="utf-8")
    out = knowledge.extract_text_from_file(f)
    assert "Hello" in out and "bold" in out and "\\rtf1" not in out


def test_corrupt_docx_raises_extraction_error(tmp_path):
    f = tmp_path / "broken.docx"
    f.write_bytes(b"this is not a zip")
    with pytest.raises(knowledge.ExtractionError):
        knowledge.extract_text_from_file(f)


# --------------------------------------------------------------------------- #
#  P0-6 — response styles
# --------------------------------------------------------------------------- #
def test_style_sections():
    assert prompts.style_section("") == ""
    assert prompts.style_section("normal") == ""
    concise = prompts.style_section("concise")
    assert "# RESPONSE STYLE" in concise and "brief" in concise.lower()
    custom = prompts.style_section("Answer like a pirate.")
    assert "Answer like a pirate." in custom
    full = prompts.build_system_prompt(style="formal")
    assert "RESPONSE STYLE" in full and "professional" in full.lower()
    assert "RESPONSE STYLE" not in prompts.build_system_prompt()


def test_turn_request_bounds_style():
    from app.schemas import AgentTurnRequest
    assert AgentTurnRequest(goal="g", model="m", style="concise").style == "concise"
    with pytest.raises(ValueError):
        AgentTurnRequest(goal="g", model="m", style="x" * 2001)


# --------------------------------------------------------------------------- #
#  P1-1 — provider-reported usage + native reasoning
# --------------------------------------------------------------------------- #
def test_usage_of_reads_provider_shapes():
    chunk = types.SimpleNamespace(usage=types.SimpleNamespace(
        prompt_tokens=120, completion_tokens=30))
    assert agent._usage_of(chunk) == {"prompt_tokens": 120, "completion_tokens": 30}
    assert agent._usage_of(types.SimpleNamespace(usage=None)) is None
    assert agent._usage_of(types.SimpleNamespace()) is None


def test_build_usage_prefers_reported_numbers():
    msgs = [{"role": "user", "content": "hi"}]
    est = usage.build_usage("glm-4-plus", msgs, "out")
    assert est["source"] == "estimated"

    rep = usage.build_usage("claude-sonnet-x", msgs, "out",
                            reported={"input": 1_000_000, "output": 1_000_000,
                                      "last_prompt": 400, "rounds": 3})
    assert rep["source"] == "reported"
    assert rep["context_tokens"] == 400          # final round's context, not the sum
    assert rep["output_tokens"] == 1_000_000
    # Billed across ALL rounds at claude-sonnet list prices: 3.00 + 15.00.
    assert rep["cost_usd"] == pytest.approx(18.0)


def _drive(gen):
    async def _collect():
        return [ev async for ev in gen]
    return asyncio.run(_collect())


def test_run_turn_folds_reported_usage_and_maps_reasoning(monkeypatch):
    """The turn's usage event uses provider numbers folded across rounds, and a
    reasoning-capable model gets a native reasoning effort on the main loop."""
    monkeypatch.setattr(agent, "resolve_turn_client",
                        lambda model, provider=None: (object(), model, None))
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)
    seen = {}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **kw):
        seen["reasoning"] = kw.get("reasoning")
        yield {"type": "delta", "scope": "answer", "text": "done"}
        yield {"__done__": {"content": "done", "tool_calls": [], "note": None,
                            "usage": {"prompt_tokens": 500, "completion_tokens": 40}}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)
    # "o3-mini" matches the o3 catalog rule -> native reasoning; Low -> "low".
    events = _drive(agent.run_turn("hi", [], None, "o3-mini", effort="Low"))
    assert seen["reasoning"] == "low"
    u = next(e for e in events if e.get("type") == "usage")
    assert u["source"] == "reported"
    assert u["context_tokens"] == 500 and u["output_tokens"] == 40

    # A plain model gets no native reasoning and estimated usage when none reported.
    async def _fake_plain(llm, model, messages, tools, temperature, max_tokens,
                          content_scope="answer", fallback_model=None, **kw):
        seen["reasoning2"] = kw.get("reasoning")
        yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_plain)
    events = _drive(agent.run_turn("hi", [], None, "plainmodel", effort="Low"))
    assert seen["reasoning2"] is None
    u = next(e for e in events if e.get("type") == "usage")
    assert u["source"] == "estimated"


# --------------------------------------------------------------------------- #
#  P1-4 — search_past_chats
# --------------------------------------------------------------------------- #
def test_past_chats_tool_gated_on_turn_id_and_setting(monkeypatch):
    monkeypatch.setattr(agent, "resolve_turn_client",
                        lambda model, provider=None: (object(), model, None))
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)
    monkeypatch.setattr(agent.auth_flows, "enabled", lambda: False)
    captured = {}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **kw):
        captured.setdefault("tools", [t["function"]["name"] for t in tools])
        yield {"__done__": {"content": "done", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    # No turn_id (background run): never offered.
    _drive(agent.run_turn("hi", [], None, "m", effort="Low"))
    assert "search_past_chats" not in captured["tools"]

    # Interactive + enabled (default): offered.
    captured.clear()
    monkeypatch.setattr(agent.settings, "get_settings",
                        lambda: {"permission_mode": "auto", "memory_search": True})
    _drive(agent.run_turn("hi", [], None, "m", effort="Low", turn_id="t1",
                          permission_mode="auto"))
    assert "search_past_chats" in captured["tools"]

    # Interactive + disabled: not offered.
    captured.clear()
    monkeypatch.setattr(agent.settings, "get_settings",
                        lambda: {"permission_mode": "auto", "memory_search": False})
    _drive(agent.run_turn("hi", [], None, "m", effort="Low", turn_id="t1",
                          permission_mode="auto"))
    assert "search_past_chats" not in captured["tools"]


def test_past_chats_dispatch_formats_hits(monkeypatch):
    hits = [{"title": "Tax plan", "project_name": "Taxes", "updated_rel": "2d ago",
             "matched_in": "body", "snippet": "…the deduction…"}]
    monkeypatch.setattr("ocd_core.conversations.search_conversations",
                        lambda q, limit: hits)
    out = asyncio.run(agent._run_one_tool(
        "search_past_chats", {"query": "deduction"}, "c1", None, "goal", 6))
    assert out["ok"] and "Tax plan" in out["result"] and out["summary"] == "1 chat"


def test_past_chats_is_read_only_safe():
    from ocd_core import permissions
    assert permissions.is_sensitive("search_past_chats") is False


# --------------------------------------------------------------------------- #
#  P1-3 — connectors directory
# --------------------------------------------------------------------------- #
def test_connector_directory_entries_are_well_formed():
    from ocd_core import connector_directory
    entries = connector_directory.list_directory()
    assert len(entries) >= 8
    for e in entries:
        assert e["id"] and e["name"] and e["description"]
        assert e["transport"] == "stdio"
        assert e["command"] in ("npx", "uvx")
        assert isinstance(e["env_keys"], list)
    # Mutating a returned entry must not poison the catalog.
    entries[0]["name"] = "hacked"
    assert connector_directory.list_directory()[0]["name"] != "hacked"


# --------------------------------------------------------------------------- #
#  P1-7 — skill supporting assets survive import and removal
# --------------------------------------------------------------------------- #
def test_skill_assets_imported_and_removed(tmp_path, monkeypatch):
    from ocd_core import skills as sk
    skills_dir = tmp_path / "skills"
    monkeypatch.setattr(sk, "_dir", lambda: skills_dir)

    repo = tmp_path / "repo" / "skills" / "report-writer"
    (repo / "references").mkdir(parents=True)
    (repo / "SKILL.md").write_text(
        "---\nname: report-writer\ndescription: writes reports\n---\nDo the thing.",
        encoding="utf-8")
    (repo / "references" / "style.md").write_text("Use headings.", encoding="utf-8")

    res = sk._import_tree(tmp_path / "repo", "repository")
    assert res["ok"] and "report-writer" in res["names"]
    copied = list(skills_dir.rglob("style.md"))
    assert copied and "references" in str(copied[0])

    sk.remove_skill("report-writer")
    assert not list(skills_dir.rglob("style.md"))  # assets cleaned with the skill
