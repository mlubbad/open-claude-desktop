"""Full-text conversation search: title + body matches, readable-text extraction
from JSON block transcripts, snippets, role attribution, and empty/no-match cases."""
import json

from ocd_core import conversations as cv


def _assistant_blocks_message(*, answer="", thinking="", artifact_title="", artifact_content=""):
    blocks = []
    if thinking:
        blocks.append({"kind": "thinking", "text": thinking})
    if answer:
        blocks.append({"kind": "answer", "text": answer})
    if artifact_title or artifact_content:
        blocks.append({"kind": "artifact", "doc": {"title": artifact_title, "content": artifact_content}})
    return {"role": "assistant", "content": json.dumps(blocks), "kind": "blocks"}


def test_message_text_extracts_readable_text_from_blocks():
    m = _assistant_blocks_message(answer="the capital is Paris", thinking="let me recall",
                                  artifact_title="Map", artifact_content="<svg>France</svg>")
    text = cv._message_text(m)
    assert "the capital is Paris" in text
    assert "let me recall" in text
    assert "Map" in text and "France" in text


def test_message_text_plain_user_message():
    assert cv._message_text({"role": "user", "content": "hello there", "kind": "user"}) == "hello there"


def test_search_matches_title(db):
    conv = cv.create_conversation("p1", "Rails deployment plan")
    hits = cv.search_conversations("deployment")
    assert len(hits) == 1
    assert hits[0]["id"] == conv["id"]
    assert hits[0]["matched_in"] == "title"
    assert "project_name" in hits[0] and "snippet" in hits[0]


def test_search_matches_assistant_block_body(db):
    conv = cv.create_conversation("p1", "greeting")
    cv.save_conversation("p1", conv["id"], [
        {"role": "user", "content": "what is the capital of France?", "kind": "user"},
        _assistant_blocks_message(answer="The capital of France is Paris, a lovely city."),
    ])
    hits = cv.search_conversations("lovely city")
    assert len(hits) == 1
    assert hits[0]["id"] == conv["id"]
    assert hits[0]["matched_in"] == "assistant"
    assert "lovely city" in hits[0]["snippet"]


def test_search_is_case_insensitive(db):
    cv.create_conversation("p1", "Kubernetes Notes")
    assert len(cv.search_conversations("kubernetes")) == 1
    assert len(cv.search_conversations("KUBERNETES")) == 1


def test_search_empty_query_returns_nothing(db):
    cv.create_conversation("p1", "anything")
    assert cv.search_conversations("") == []
    assert cv.search_conversations("   ") == []


def test_search_no_match_returns_empty(db):
    cv.create_conversation("p1", "hello world")
    assert cv.search_conversations("zzz-no-such-term") == []


def test_search_respects_limit(db):
    for i in range(5):
        cv.create_conversation("p1", f"widget number {i}")
    hits = cv.search_conversations("widget", limit=3)
    assert len(hits) == 3


def test_search_snippet_has_context_window(db):
    conv = cv.create_conversation("p1", "log")
    long = "prefix " * 20 + "NEEDLE" + " suffix" * 20
    cv.save_conversation("p1", conv["id"], [{"role": "user", "content": long, "kind": "user"}])
    hits = cv.search_conversations("NEEDLE")
    assert len(hits) == 1
    snip = hits[0]["snippet"]
    assert "NEEDLE" in snip
    assert snip.startswith("…") and snip.endswith("…")  # trimmed on both sides
