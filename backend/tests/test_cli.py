"""The `ocd` CLI: pure event renderer, JSONL mode, arg parsing, history mapping, and
the REPL slash-command parser. No network / LLM calls — the render + parse layers are
exercised directly with synthetic events."""
import json

from ocd_cli import cli
from ocd_cli.render import Renderer, json_line
from ocd_cli.repl import parse_command


def _plain(ev) -> str:
    return Renderer(color=False).feed(ev)


def test_renderer_answer_and_think_deltas():
    r = Renderer(color=False)
    assert r.feed({"type": "answer_open"}) == "\n"
    assert r.feed({"type": "delta", "scope": "answer", "text": "Hello"}) == "Hello"
    assert r.feed({"type": "delta", "scope": "think", "text": "hmm"}) == "hmm"


def test_renderer_tool_and_result():
    out = _plain({"type": "tool", "name": "web_search", "input": "cats"})
    assert "web_search" in out and "cats" in out
    assert "✓ 3 results" in _plain({"type": "tool_result", "summary": "3 results"})
    assert "✗" in _plain({"type": "tool_error", "text": "boom"})


def test_renderer_artifact_and_usage():
    assert "📄 Chart [html]" in _plain({"type": "artifact_open", "title": "Chart", "kind": "html"})
    usage = _plain({"type": "usage", "output_tokens": 1200, "context_tokens": 3400,
                    "context_limit": 128000, "cost_usd": 0.0021})
    assert "1,200 out" in usage and "$0.0021" in usage


def test_renderer_table():
    out = _plain({"type": "table", "columns": ["n", "name"],
                  "rows": [{"n": 1, "name": "a"}, {"n": 2, "name": "b"}], "total": 2, "bytes": 8})
    assert "n" in out and "name" in out and "a" in out and "b" in out


def test_renderer_color_wraps_in_ansi_only_when_enabled():
    colored = Renderer(color=True).feed({"type": "tool_error", "text": "x"})
    assert "\x1b[" in colored
    assert "\x1b[" not in Renderer(color=False).feed({"type": "tool_error", "text": "x"})


def test_json_line_roundtrips():
    ev = {"type": "delta", "scope": "answer", "text": "hi"}
    assert json.loads(json_line(ev)) == ev


def test_arg_parser_headless_and_flags():
    args = cli.build_parser().parse_args(["-p", "hello", "world", "-m", "gpt-4o", "--json"])
    assert args.headless is True and args.json is True
    assert args.prompt == ["hello", "world"] and args.model == "gpt-4o"


def test_arg_parser_resume_and_continue():
    a = cli.build_parser().parse_args(["--resume", "abc123"])
    assert a.resume == "abc123"
    b = cli.build_parser().parse_args(["-c"])
    assert b.cont is True


def test_history_from_maps_role_content():
    msgs = [
        {"role": "user", "content": "q1", "kind": "user"},
        {"role": "assistant", "content": "a1", "kind": "final"},
        {"role": "tool", "content": "ignored", "kind": "tool"},
    ]
    assert cli._history_from(msgs) == [
        {"role": "user", "content": "q1"},
        {"role": "assistant", "content": "a1"},
    ]


def test_repl_parse_command_classifies():
    assert parse_command("") == ("empty", "")
    assert parse_command("hello there") == ("chat", "hello there")
    assert parse_command("/model gpt-4o") == ("cmd", ("model", "gpt-4o"))
    assert parse_command("/quit") == ("cmd", ("quit", ""))
    # An unknown /name is NOT a REPL command — it flows to the agent (skill resolution).
    assert parse_command("/summarize this doc") == ("chat", "/summarize this doc")
