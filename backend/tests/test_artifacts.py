"""Phase 3: artifact tool execution + the artifact_open/delta/close event derivation."""
import asyncio

import pytest
from ocd_core import agent, artifact_tools, secrets
from ocd_core.llm import client as llm_client


def test_create_and_update_store():
    store: dict = {}
    a = artifact_tools.create(
        {"title": "Chart", "kind": "html", "content": "<h1>hi</h1>"}, store)
    assert a["id"] == "art1" and a["version"] == 1 and a["kind"] == "html"
    b, err = artifact_tools.update({"id": "art1", "content": "<h1>bye</h1>"}, store)
    assert err is None and b["version"] == 2 and store["art1"]["content"] == "<h1>bye</h1>"
    _, err2 = artifact_tools.update({"id": "nope", "content": "x"}, store)
    assert err2 is not None


def test_unknown_kind_falls_back_to_markdown():
    a = artifact_tools.create({"title": "x", "kind": "banana", "content": "y"}, {})
    assert a["kind"] == "markdown"


def test_csv_is_a_creatable_kind():
    # The model must be able to hand back tabular data as a downloadable table artifact
    # (kind=csv) instead of pasting rows into the chat reply.
    a = artifact_tools.create(
        {"title": "Merged", "kind": "csv", "content": "a,b\n1,2"}, {})
    assert a["kind"] == "csv"
    assert "csv" in artifact_tools.KINDS


FENCED_XYCHART = (
    "```mermaid\n"
    "xychart-beta\n"
    '    title "Top Series by Hours Watched (2026-07-19)"\n'
    '    x-axis ["الدحيح (Mobile)", "أبو الصادق (Mobile)"]\n'
    '    y-axis "Hours Watched" 0 --> 1000\n'
    "    bar [978.8, 736.5]\n"
    "```"
)


class TestStripCodeFence:
    """Models routinely wrap tool-call content in markdown fences; ingestion unwraps a
    single whole-content fence so renderers see raw source (the reported mermaid
    'Syntax error in text' incident)."""

    def test_unwraps_language_fence(self):
        body = artifact_tools.strip_code_fence(FENCED_XYCHART)
        assert body.startswith("xychart-beta")
        assert body.endswith("bar [978.8, 736.5]")
        assert "```" not in body

    def test_unwraps_bare_fence(self):
        assert artifact_tools.strip_code_fence("```\nhello\n```") == "hello"

    def test_tilde_fences_untouched(self):
        s = "~~~\nhello\n~~~"
        assert artifact_tools.strip_code_fence(s) == s

    def test_unfenced_unchanged(self):
        s = "graph TD; A --> B;"
        assert artifact_tools.strip_code_fence(s) == s

    def test_fence_plus_trailing_prose_unchanged(self):
        s = "```python\nprint(1)\n```\nAnd here is why."
        assert artifact_tools.strip_code_fence(s) == s

    def test_outer_strip_keeps_inner_fences(self):
        s = "```markdown\n# Doc\n\n```py\nprint(1)\n```\n\ntail\n```"
        assert (artifact_tools.strip_code_fence(s)
                == "# Doc\n\n```py\nprint(1)\n```\n\ntail")

    def test_crlf_fence_unwraps(self):
        assert artifact_tools.strip_code_fence("```mermaid\r\npie\r\n```") == "pie"

    def test_no_trailing_newline_before_closer(self):
        assert artifact_tools.strip_code_fence("```js\nlet x = 1;```") == "let x = 1;"

    def test_create_strips_fence(self):
        a = artifact_tools.create(
            {"title": "Chart", "kind": "mermaid", "content": FENCED_XYCHART}, {})
        assert a["content"].startswith("xychart-beta") and "```" not in a["content"]

    def test_update_full_content_strips_fence(self):
        store: dict = {}
        artifact_tools.create({"title": "D", "kind": "mermaid", "content": "pie"}, store)
        b, err = artifact_tools.update(
            {"id": "art1", "content": "```mermaid\nflowchart TD; A --> B;\n```"}, store)
        assert err is None
        assert b["content"] == "flowchart TD; A --> B;"


class TestTargetedUpdate:
    """Claude Gen-2 `update` semantics: old_str/new_str replacement with the
    exactly-once contract; full `content` remains the rewrite path."""

    def _store(self) -> dict:
        store: dict = {}
        artifact_tools.create(
            {"title": "Doc", "kind": "markdown",
             "content": "# Title\n\nalpha\nbeta\ngamma\n"}, store)
        return store

    def test_old_str_replaces_and_bumps_version(self):
        store = self._store()
        doc, err = artifact_tools.update(
            {"id": "art1", "old_str": "beta", "new_str": "BETA"}, store)
        assert err is None
        assert doc["version"] == 2
        assert store["art1"]["content"] == "# Title\n\nalpha\nBETA\ngamma\n"

    def test_old_str_not_found_errors(self):
        doc, err = artifact_tools.update(
            {"id": "art1", "old_str": "delta", "new_str": "x"}, self._store())
        assert doc is None and err is not None and "not found" in err

    def test_ambiguous_old_str_errors_with_count(self):
        store: dict = {}
        artifact_tools.create(
            {"title": "D", "kind": "markdown", "content": "x y x"}, store)
        doc, err = artifact_tools.update(
            {"id": "art1", "old_str": "x", "new_str": "z"}, store)
        assert doc is None and err is not None
        assert "2" in err and "unique" in err
        assert store["art1"]["content"] == "x y x"  # unchanged on error
        assert store["art1"]["version"] == 1

    def test_full_content_wins_over_old_str(self):
        store = self._store()
        doc, err = artifact_tools.update(
            {"id": "art1", "content": "rewritten", "old_str": "alpha",
             "new_str": "A"}, store)
        assert err is None and doc["content"] == "rewritten"

    def test_new_str_is_literal_not_fence_stripped(self):
        store = self._store()
        doc, err = artifact_tools.update(
            {"id": "art1", "old_str": "beta", "new_str": "```code```"}, store)
        assert err is None and "```code```" in doc["content"]

    def test_empty_new_str_deletes(self):
        store = self._store()
        doc, err = artifact_tools.update(
            {"id": "art1", "old_str": "beta\n", "new_str": ""}, store)
        assert err is None
        assert doc["content"] == "# Title\n\nalpha\ngamma\n"

    def test_schema_declares_targeted_fields(self):
        props = artifact_tools.UPDATE_ARTIFACT_TOOL["function"]["parameters"]["properties"]
        assert "old_str" in props and "new_str" in props
        required = artifact_tools.UPDATE_ARTIFACT_TOOL["function"]["parameters"]["required"]
        assert "content" not in required and "id" in required

    def test_update_with_neither_content_nor_old_str_errors(self):
        doc, err = artifact_tools.update({"id": "art1"}, self._store())
        assert doc is None and err is not None


class TestSystemPromptSection:
    """The prompt must carry Claude's artifact criteria plus truthful per-kind rules
    for THIS runtime (roster kept in sync with the desktop import map)."""

    def setup_method(self):
        self.text = artifact_tools.system_prompt_section()

    def test_thresholds_and_one_per_message(self):
        assert "20 lines" in self.text
        assert "one artifact per message" in self.text.lower()

    def test_no_fence_rule(self):
        assert "```" in self.text and "fence" in self.text.lower()

    def test_mermaid_label_quoting_rule(self):
        assert "double-quote" in self.text.lower()
        assert "xychart" in self.text.lower()

    def test_react_rules_and_roster(self):
        for needle in ("default export", "localStorage", "recharts", "lucide-react",
                       "d3", "papaparse", "Tailwind"):
            assert needle in self.text, needle

    def test_html_and_svg_rules(self):
        assert "single" in self.text.lower() and "cdn" in self.text.lower()
        assert "viewBox" in self.text

    def test_targeted_update_guidance(self):
        assert "old_str" in self.text

    def test_keeps_csv_and_file_writing_guidance(self):
        assert "kind=csv" in self.text
        assert "code_execution" in self.text
        for ext in ("xlsx", "docx", "pptx", "pdf"):
            assert ext in self.text, ext


def test_completion_events_emit_artifact_triple():
    out = {
        "id": "c1", "name": "create_artifact", "ok": True, "summary": "Chart · html",
        "artifact": {"id": "art1", "title": "Chart", "kind": "html", "language": "",
                     "content": "<h1>hi</h1>", "version": 1},
    }
    evs = agent._completion_events(out)
    types = [e["type"] for e in evs]
    assert types == ["tool_result", "artifact_open", "artifact_delta", "artifact_close"]
    opened = next(e for e in evs if e["type"] == "artifact_open")
    assert opened["title"] == "Chart" and opened["kind"] == "html"
    delta = next(e for e in evs if e["type"] == "artifact_delta")
    assert delta["text"] == "<h1>hi</h1>"


@pytest.fixture
def _env(monkeypatch):
    monkeypatch.setenv("OCD_SECRET_BACKEND", "memory")
    secrets.reset_store()
    llm_client.reset_clients()
    monkeypatch.setattr(agent, "resolve_turn_client",
                        lambda model, provider=None: (object(), model, None))
    monkeypatch.setattr(agent.schema_catalog, "ensure_catalog", lambda: None)
    yield
    secrets.reset_store()
    llm_client.reset_clients()


class _FakeToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = type("F", (), {"name": name, "arguments": arguments})()

    def model_dump(self):
        return {"id": self.id, "type": "function",
                "function": {"name": self.function.name, "arguments": self.function.arguments}}


def test_run_turn_streams_artifact_events(monkeypatch, _env):
    import json
    state = {"n": 0}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        state["n"] += 1
        if state["n"] == 1:
            args = json.dumps({"title": "Page", "kind": "html", "content": "<p>x</p>"})
            yield {"__done__": {"content": "", "note": None,
                                "tool_calls": [_FakeToolCall("c1", "create_artifact", args)]}}
        else:
            yield {"type": "delta", "scope": "answer", "text": "Made a page."}
            yield {"__done__": {"content": "Made a page.", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        return [ev async for ev in agent.run_turn(
            "make a page", [], None, "m", effort="Low", artifacts=True)]

    types = [e["type"] for e in asyncio.run(scenario())]
    assert "artifact_open" in types and "artifact_delta" in types and "artifact_close" in types


def test_artifacts_off_by_default_in_run_turn(monkeypatch, _env):
    seen = {}

    async def _fake_stream(llm, model, messages, tools, temperature, max_tokens,
                           content_scope="answer", fallback_model=None, **_kw):
        seen["tools"] = [t["function"]["name"] for t in (tools or [])]
        yield {"__done__": {"content": "hi", "tool_calls": [], "note": None}}

    monkeypatch.setattr(agent, "_stream_llm", _fake_stream)

    async def scenario():
        async for _ in agent.run_turn("hi", [], None, "m", effort="Low"):
            pass
    asyncio.run(scenario())
    assert "create_artifact" not in seen["tools"]
