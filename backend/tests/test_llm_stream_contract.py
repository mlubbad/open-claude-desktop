"""Phase 1 contract test: the OpenAI-compatible streaming shape parses correctly.

Mocks an OpenAI-compatible ``/chat/completions`` SSE stream (the shape every
provider — Zhipu, DeepSeek, Ollama, … — speaks) and drives it through the real
client, asserting that content deltas, reasoning/thinking deltas, tool-call
assembly, and usage all come through as the agent loop expects. This replaces a
provider-SDK-pinned test with a provider-shape contract.
"""
import json

import httpx
import pytest
import respx
from ocd_core import llm, secrets
from ocd_core.llm import client as llm_client
from ocd_core.llm import keys as llm_keys


@pytest.fixture(autouse=True)
def _mem_store(monkeypatch):
    monkeypatch.setenv("OCD_SECRET_BACKEND", "memory")
    secrets.reset_store()
    llm_client.reset_clients()
    llm_keys.set_api_key("deepseek", "sk-test")
    yield
    secrets.reset_store()
    llm_client.reset_clients()


def _chunk(**delta):
    return {"id": "c", "object": "chat.completion.chunk", "created": 0,
            "model": "deepseek-chat",
            "choices": [{"index": 0, "delta": delta, "finish_reason": None}]}


def _sse(*chunks) -> str:
    lines = [f"data: {json.dumps(c)}\n\n" for c in chunks]
    lines.append("data: [DONE]\n\n")
    return "".join(lines)


@respx.mock
def test_streaming_content_reasoning_and_tool_calls():
    body = _sse(
        _chunk(reasoning_content="Let me think. "),
        _chunk(content="Hello"),
        _chunk(content=" world"),
        _chunk(tool_calls=[{"index": 0, "id": "t1", "type": "function",
                            "function": {"name": "search_schema", "arguments": '{"q":'}}]),
        _chunk(tool_calls=[{"index": 0, "function": {"arguments": '"x"}'}}]),
    )
    respx.post("https://api.deepseek.com/chat/completions").mock(
        return_value=httpx.Response(200, text=body,
                                    headers={"content-type": "text/event-stream"}))

    client = llm.get_client("deepseek")
    stream = client.chat.completions.create(
        model="deepseek-chat", stream=True,
        messages=[{"role": "user", "content": "hi"}])

    content, reasoning, tool_args, tool_name = [], [], [], None
    for chunk in stream:
        delta = chunk.choices[0].delta
        if getattr(delta, "content", None):
            content.append(delta.content)
        rc = llm.reasoning_of(delta)
        if rc:
            reasoning.append(rc)
        for tc in (getattr(delta, "tool_calls", None) or []):
            if tc.function and tc.function.name:
                tool_name = tc.function.name
            if tc.function and tc.function.arguments:
                tool_args.append(tc.function.arguments)

    assert "".join(content) == "Hello world"
    assert "".join(reasoning) == "Let me think. "
    assert tool_name == "search_schema"
    assert json.loads("".join(tool_args)) == {"q": "x"}


@respx.mock
def test_non_streaming_message():
    resp = {"id": "c", "object": "chat.completion", "created": 0, "model": "deepseek-chat",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": "A short title"}}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}}
    respx.post("https://api.deepseek.com/chat/completions").mock(
        return_value=httpx.Response(200, json=resp))

    client = llm.get_client("deepseek")
    out = client.chat.completions.create(
        model="deepseek-chat", messages=[{"role": "user", "content": "hi"}])
    assert out.choices[0].message.content == "A short title"
    assert out.usage.total_tokens == 8
