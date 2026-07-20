"""Gemini thought signatures survive the streaming tool-call reassembly.

Google's OpenAI-compat endpoints (gemini, vertex) attach an encrypted thought
signature to tool calls as ``tool_calls[i].extra_content.google.thought_signature``,
and Gemini 3 models REJECT the next request in the turn (400 INVALID_ARGUMENT,
"Function call is missing a thought_signature") unless the replayed assistant
message carries it back verbatim on the same call. Parallel calls carry the
signature only on the FIRST call — the companions must stay signature-free.
Contract: https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures

These drive the real ``_stream_llm`` reassembly with SDK-parsed chunks (the same
objects ``_stream_chunks`` yields), asserting on the ``model_dump()`` shape that
``run_turn`` replays as conversation history.
"""
import asyncio
import types

from ocd_core import agent
from openai.types.chat import ChatCompletionChunk

_SIG = {"google": {"thought_signature": "sig-A"}}


def _sdk_chunk(delta: dict):
    """A chunk exactly as the openai SDK parses it off the wire (extra fields kept)."""
    return ChatCompletionChunk.model_validate({
        "id": "c", "object": "chat.completion.chunk", "created": 0,
        "model": "gemini-3.1-pro-preview",
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}]})


async def _gemini_chunks(*_a, **_k):
    # Parallel tool calls, Gemini 3 shape: the signature rides extra_content on the
    # first call only; its arguments arrive split across two deltas.
    yield _sdk_chunk({"tool_calls": [
        {"index": 0, "id": "fc-1", "type": "function",
         "function": {"name": "run_sql", "arguments": '{"sql":'},
         "extra_content": _SIG}]})
    yield _sdk_chunk({"tool_calls": [
        {"index": 0, "function": {"arguments": '"SELECT 1"}'}},
        {"index": 1, "id": "fc-2", "type": "function",
         "function": {"name": "run_sql", "arguments": "{}"}}]})


def _done_of(monkeypatch, chunks):
    monkeypatch.setattr(agent, "_stream_chunks", chunks)

    async def run():
        async for ev in agent._stream_llm(None, "gemini-3.1-pro-preview", [], tools=[]):
            if "__done__" in ev:
                return ev["__done__"]

    return asyncio.run(run())


def test_stream_llm_preserves_thought_signature_on_first_call(monkeypatch):
    done = _done_of(monkeypatch, _gemini_chunks)
    d0 = done["tool_calls"][0].model_dump()
    assert d0["extra_content"] == _SIG
    # Reassembly is otherwise unchanged: id kept, split arguments merged.
    assert d0["id"] == "fc-1"
    assert d0["function"] == {"name": "run_sql", "arguments": '{"sql":"SELECT 1"}'}


def test_parallel_companion_call_stays_signature_free(monkeypatch):
    done = _done_of(monkeypatch, _gemini_chunks)
    d1 = done["tool_calls"][1].model_dump()
    assert "extra_content" not in d1  # replay must match what was received


def test_dump_shape_unchanged_for_providers_without_signatures(monkeypatch):
    # Non-Google providers (SimpleNamespace deltas: no extra_content, no model_extra).
    async def plain_chunks(*_a, **_k):
        tc = types.SimpleNamespace(index=0, id="t1", function=types.SimpleNamespace(
            name="search_schema", arguments='{"q":"x"}'))
        delta = types.SimpleNamespace(content=None, tool_calls=[tc])
        yield types.SimpleNamespace(choices=[types.SimpleNamespace(delta=delta)])

    done = _done_of(monkeypatch, plain_chunks)
    assert set(done["tool_calls"][0].model_dump()) == {"id", "type", "function"}
