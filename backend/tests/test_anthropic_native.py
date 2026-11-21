"""Native Anthropic adapter (P2): the OpenAI-compatible facade over the Messages
API must translate faithfully in both directions — request shaping per model
family (adaptive vs budget thinking, sampling-param rejection, cache_control
breakpoints), and SSE events back into the exact chunk attributes the agent loop
reads. Streaming tests go through the REAL anthropic SDK against an httpx mock
transport, so the wire format is exercised, not assumed."""
import json

import anthropic
import httpx
import pytest
from ocd_core.llm import anthropic_native as an
from ocd_core.llm.anthropic_native import AnthropicNativeClient


# --------------------------------------------------------------------------- #
#  Harness: a facade whose SDK client talks to a canned httpx transport
# --------------------------------------------------------------------------- #
def _sse(events: list[dict]) -> bytes:
    out = []
    for ev in events:
        out.append(f"event: {ev['type']}\ndata: {json.dumps(ev)}\n\n")
    return "".join(out).encode()


def make_client(monkeypatch, *, sse_events=None, json_body=None, status=200,
                captured: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if captured is not None:
            captured.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, json={
                "type": "error",
                "error": {"type": "rate_limit_error", "message": "slow down"}})
        if sse_events is not None:
            return httpx.Response(200, content=_sse(sse_events),
                                  headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json=json_body)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = AnthropicNativeClient(api_key="test-key")
    monkeypatch.setattr(client._client, "_client", http_client)
    return client


def _message_json(content: list[dict], stop_reason="end_turn") -> dict:
    return {"id": "msg_1", "type": "message", "role": "assistant",
            "model": "claude-sonnet-5", "content": content,
            "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5,
                      "cache_read_input_tokens": 7,
                      "cache_creation_input_tokens": 3}}


@pytest.fixture(autouse=True)
def _clear_thinking_cache():
    an._THINKING_CACHE.clear()


# --------------------------------------------------------------------------- #
#  Model families
# --------------------------------------------------------------------------- #
def test_family_classification():
    assert an._family("claude-fable-5") == "always"
    assert an._family("claude-mythos-5") == "always"
    assert an._family("claude-sonnet-5") == "adaptive"
    assert an._family("claude-opus-4-7") == "adaptive"
    assert an._family("claude-opus-4-6") == "adaptive"
    assert an._family("claude-sonnet-4-6") == "adaptive"
    assert an._family("claude-sonnet-4-5-20250929") == "budget"
    assert an._family("claude-haiku-4-5") == "budget"
    assert an._family("claude-3-7-sonnet-20250219") == "budget"
    assert an._family("claude-3-5-haiku-20241022") == "budget"


def test_sampling_rejection_set():
    assert an._rejects_sampling("claude-fable-5")
    assert an._rejects_sampling("claude-opus-4-7")
    assert an._rejects_sampling("claude-sonnet-5")
    assert not an._rejects_sampling("claude-opus-4-6")
    assert not an._rejects_sampling("claude-sonnet-4-5")


# --------------------------------------------------------------------------- #
#  Request shaping
# --------------------------------------------------------------------------- #
def _shape(monkeypatch, model, *, reasoning=None, temperature=0.1,
           messages=None, tools=None):
    captured: list = []
    client = make_client(monkeypatch, json_body=_message_json(
        [{"type": "text", "text": "hi"}]), captured=captured)
    client.chat.completions.create(
        model=model,
        messages=messages or [{"role": "system", "content": "You are helpful."},
                              {"role": "user", "content": "hello"}],
        tools=tools, temperature=temperature, max_tokens=4096,
        reasoning_effort=reasoning)
    return captured[0]


def test_adaptive_model_gets_adaptive_thinking_and_effort(monkeypatch):
    body = _shape(monkeypatch, "claude-sonnet-5", reasoning="high")
    assert body["thinking"] == {"type": "adaptive", "display": "summarized"}
    assert body["output_config"] == {"effort": "high"}
    assert "temperature" not in body  # rejected on 5-series


def test_always_on_model_never_sends_thinking_config_off(monkeypatch):
    body = _shape(monkeypatch, "claude-fable-5", reasoning=None)
    # Thinking cannot be disabled; keep the summarized display so the UI's think
    # scope renders, and never send sampling params.
    assert body["thinking"]["type"] == "adaptive"
    assert "temperature" not in body


def test_budget_model_gets_budget_tokens_with_headroom(monkeypatch):
    body = _shape(monkeypatch, "claude-sonnet-4-5", reasoning="medium")
    assert body["thinking"] == {"type": "enabled", "budget_tokens": 8192}
    assert body["max_tokens"] > 8192  # answer keeps its own room
    assert "temperature" not in body  # required off while thinking
    assert "output_config" not in body  # effort errors on this model


def test_adaptive_model_disables_thinking_without_reasoning(monkeypatch):
    # Omitting `thinking` on a 4.6+/5-series model runs adaptive-on by default,
    # which would burn a 400-token plan pass on hidden thinking. Turn it off.
    body = _shape(monkeypatch, "claude-opus-4-6", reasoning=None)
    assert body["thinking"] == {"type": "disabled"}
    assert body["temperature"] == 0.1  # allowed once thinking is off


def test_no_trailing_assistant_prefill(monkeypatch):
    # The agent's plan pass ends history on an assistant turn; the adapter must not
    # send that as a prefill (400 on modern models) — it appends a user continuation.
    body = _shape(monkeypatch, "claude-sonnet-5",
                  messages=[{"role": "system", "content": "sys"},
                            {"role": "user", "content": "goal"},
                            {"role": "assistant", "content": "My plan: do X."}])
    assert body["messages"][-1]["role"] == "user"
    assert body["messages"][-1]["content"][0]["text"] == "Continue."
    # The plan itself survives as assistant context (only the LAST turn was fixed).
    assert body["messages"][-2]["role"] == "assistant"


def test_thinking_calls_get_max_tokens_headroom(monkeypatch):
    # A tiny answer budget (the 400-token plan/verify passes) must not be swallowed
    # whole by thinking tokens — the adapter floors the total.
    captured: list = []
    client = make_client(monkeypatch, json_body=_message_json(
        [{"type": "text", "text": "ok"}]), captured=captured)
    client.chat.completions.create(
        model="claude-sonnet-5", messages=[{"role": "user", "content": "hi"}],
        reasoning_effort="high", max_tokens=400)
    assert captured[0]["max_tokens"] >= 8192


def test_cache_breakpoints_on_system_and_conversation_tail(monkeypatch):
    body = _shape(monkeypatch, "claude-sonnet-5",
                  messages=[{"role": "system", "content": "sys"},
                            {"role": "user", "content": "q1"},
                            {"role": "assistant", "content": "a1"},
                            {"role": "user", "content": "q2"}])
    assert body["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert body["messages"][-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    # Exactly two breakpoints (max 4 allowed) — earlier blocks stay unmarked.
    marked = [b for m in body["messages"] for b in m["content"]
              if "cache_control" in b] + [b for b in body["system"]
                                          if "cache_control" in b]
    assert len(marked) == 2


def test_tools_and_tool_results_translate(monkeypatch):
    tools = [{"type": "function",
              "function": {"name": "web_search", "description": "Search.",
                           "parameters": {"type": "object",
                                          "properties": {"query": {"type": "string"}},
                                          "required": ["query"]}}}]
    messages = [
        {"role": "user", "content": "find cats"},
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "toolu_1", "type": "function",
                         "function": {"name": "web_search",
                                      "arguments": '{"query": "cats"}'}},
                        {"id": "toolu_2", "type": "function",
                         "function": {"name": "web_search",
                                      "arguments": '{"query": "dogs"}'}}]},
        {"role": "tool", "tool_call_id": "toolu_1", "content": "cat facts"},
        {"role": "tool", "tool_call_id": "toolu_2", "content": "dog facts"},
    ]
    body = _shape(monkeypatch, "claude-sonnet-5", messages=messages, tools=tools)
    assert body["tools"] == [{"name": "web_search", "description": "Search.",
                              "input_schema": tools[0]["function"]["parameters"]}]
    assert body["tool_choice"] == {"type": "auto"}
    # The assistant turn carries both tool_use blocks with parsed input…
    asst = body["messages"][1]
    uses = [b for b in asst["content"] if b["type"] == "tool_use"]
    assert [u["input"] for u in uses] == [{"query": "cats"}, {"query": "dogs"}]
    # …and BOTH tool results ride in ONE user message (parallel-tool-use rule).
    results = body["messages"][2]
    assert results["role"] == "user"
    assert [b["tool_use_id"] for b in results["content"]
            if b["type"] == "tool_result"] == ["toolu_1", "toolu_2"]


def test_image_data_uri_becomes_base64_block(monkeypatch):
    messages = [{"role": "user", "content": [
        {"type": "text", "text": "what is this?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,aWNvbg=="}}]}]
    body = _shape(monkeypatch, "claude-sonnet-5", messages=messages)
    img = body["messages"][0]["content"][1]
    assert img["type"] == "image"
    assert img["source"] == {"type": "base64", "media_type": "image/png",
                             "data": "aWNvbg=="}


# --------------------------------------------------------------------------- #
#  Streaming translation
# --------------------------------------------------------------------------- #
_STREAM = [
    {"type": "message_start",
     "message": {"id": "msg_1", "type": "message", "role": "assistant",
                 "model": "claude-sonnet-5", "content": [], "stop_reason": None,
                 "stop_sequence": None,
                 "usage": {"input_tokens": 10, "output_tokens": 1,
                           "cache_read_input_tokens": 7,
                           "cache_creation_input_tokens": 3}}},
    {"type": "content_block_start", "index": 0,
     "content_block": {"type": "thinking", "thinking": "", "signature": ""}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "thinking_delta", "thinking": "pondering"}},
    {"type": "content_block_delta", "index": 0,
     "delta": {"type": "signature_delta", "signature": "sig123"}},
    {"type": "content_block_stop", "index": 0},
    {"type": "content_block_start", "index": 1,
     "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 1,
     "delta": {"type": "text_delta", "text": "Hello"}},
    {"type": "content_block_stop", "index": 1},
    {"type": "content_block_start", "index": 2,
     "content_block": {"type": "tool_use", "id": "toolu_9", "name": "web_search",
                       "input": {}}},
    {"type": "content_block_delta", "index": 2,
     "delta": {"type": "input_json_delta", "partial_json": '{"query":'}},
    {"type": "content_block_delta", "index": 2,
     "delta": {"type": "input_json_delta", "partial_json": '"cats"}'}},
    {"type": "content_block_stop", "index": 2},
    {"type": "message_delta", "delta": {"stop_reason": "tool_use",
                                        "stop_sequence": None},
     "usage": {"output_tokens": 25}},
    {"type": "message_stop"},
]


def test_stream_translates_to_openai_chunks(monkeypatch):
    client = make_client(monkeypatch, sse_events=_STREAM)
    chunks = list(client.chat.completions.create(
        model="claude-sonnet-5", messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "web_search",
                                                 "parameters": {"type": "object"}}}],
        stream=True, reasoning_effort="high", max_tokens=4096))

    reasoning = "".join(c.choices[0].delta.reasoning_content or ""
                        for c in chunks if c.choices)
    content = "".join(c.choices[0].delta.content or ""
                      for c in chunks if c.choices)
    assert reasoning == "pondering"
    assert content == "Hello"

    # Tool-call deltas accumulate exactly like the agent loop expects: a first
    # delta with id+name, then argument fragments on the same index.
    acc: dict = {}
    for c in chunks:
        for tcd in (c.choices[0].delta.tool_calls or []) if c.choices else []:
            slot = acc.setdefault(tcd.index, {"id": "", "name": "", "arguments": ""})
            if tcd.id:
                slot["id"] = tcd.id
            if tcd.function.name:
                slot["name"] = tcd.function.name
            slot["arguments"] += tcd.function.arguments
    assert acc == {0: {"id": "toolu_9", "name": "web_search",
                       "arguments": '{"query":"cats"}'}}

    # Final chunk: real usage (uncached + cache reads + writes) and finish reason.
    final = chunks[-1]
    assert final.usage.prompt_tokens == 20
    assert final.usage.completion_tokens == 25
    assert final.usage.prompt_tokens_details.cached_tokens == 7
    assert final.choices[0].finish_reason == "tool_calls"


def test_stream_caches_signed_thinking_for_replay(monkeypatch):
    client = make_client(monkeypatch, sse_events=_STREAM)
    list(client.chat.completions.create(
        model="claude-sonnet-4-5", messages=[{"role": "user", "content": "hi"}],
        stream=True, reasoning_effort="high", max_tokens=4096))
    blocks = an._recall_thinking(["toolu_9"])
    assert blocks == [{"type": "thinking", "thinking": "pondering",
                       "signature": "sig123"}]

    # Translating the follow-up request re-attaches the signed block ahead of the
    # tool_use in the SAME assistant turn.
    _, msgs = an.to_anthropic_messages([
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "",
         "tool_calls": [{"id": "toolu_9", "type": "function",
                         "function": {"name": "web_search",
                                      "arguments": '{"query": "cats"}'}}]},
        {"role": "tool", "tool_call_id": "toolu_9", "content": "results"},
    ])
    asst = msgs[1]["content"]
    assert asst[0] == {"type": "thinking", "thinking": "pondering",
                       "signature": "sig123"}
    assert asst[1]["type"] == "tool_use"


def test_budget_model_disables_thinking_when_replay_blocks_are_lost(monkeypatch):
    """After an app restart mid tool-loop the signed blocks are gone; a budget-family
    request must drop `thinking` rather than 400 on the missing block."""
    captured: list = []
    client = make_client(monkeypatch, json_body=_message_json(
        [{"type": "text", "text": "done"}]), captured=captured)
    client.chat.completions.create(
        model="claude-sonnet-4-5",
        messages=[{"role": "user", "content": "hi"},
                  {"role": "assistant", "content": "",
                   "tool_calls": [{"id": "toolu_lost", "type": "function",
                                   "function": {"name": "t", "arguments": "{}"}}]},
                  {"role": "tool", "tool_call_id": "toolu_lost", "content": "r"}],
        reasoning_effort="high", max_tokens=4096)
    assert "thinking" not in captured[0]


# --------------------------------------------------------------------------- #
#  Non-streaming + errors
# --------------------------------------------------------------------------- #
def test_non_streaming_response_shape(monkeypatch):
    client = make_client(monkeypatch, json_body=_message_json(
        [{"type": "text", "text": "Hi there"},
         {"type": "tool_use", "id": "toolu_5", "name": "t", "input": {"a": 1}}],
        stop_reason="tool_use"))
    resp = client.chat.completions.create(
        model="claude-sonnet-5", messages=[{"role": "user", "content": "hi"}],
        max_tokens=64)
    msg = resp.choices[0].message
    assert msg.content == "Hi there"
    assert msg.tool_calls[0].model_dump() == {
        "id": "toolu_5", "type": "function",
        "function": {"name": "t", "arguments": '{"a": 1}'}}
    assert resp.choices[0].finish_reason == "tool_calls"
    assert resp.usage.prompt_tokens == 20  # 10 + 7 cache-read + 3 cache-write


def test_streaming_refusal_surfaces_explanation(monkeypatch):
    # A pre-output classifier refusal (empty content, stop_reason "refusal") must
    # yield a visible explanation, not a blank turn the agent loop re-sends.
    stream = [
        {"type": "message_start",
         "message": {"id": "m", "type": "message", "role": "assistant",
                     "model": "claude-fable-5", "content": [], "stop_reason": None,
                     "stop_sequence": None,
                     "usage": {"input_tokens": 5, "output_tokens": 0}}},
        {"type": "message_delta",
         "delta": {"stop_reason": "refusal", "stop_sequence": None},
         "usage": {"output_tokens": 0}},
        {"type": "message_stop"},
    ]
    client = make_client(monkeypatch, sse_events=stream)
    chunks = list(client.chat.completions.create(
        model="claude-fable-5", messages=[{"role": "user", "content": "x"}],
        stream=True, max_tokens=4096))
    text = "".join(c.choices[0].delta.content or "" for c in chunks if c.choices)
    assert "declined" in text.lower()
    assert chunks[-1].choices[0].finish_reason == "content_filter"


def test_nonstreaming_refusal_surfaces_explanation(monkeypatch):
    body = _message_json([], stop_reason="refusal")
    client = make_client(monkeypatch, json_body=body)
    resp = client.chat.completions.create(
        model="claude-fable-5", messages=[{"role": "user", "content": "x"}],
        max_tokens=64)
    assert "declined" in resp.choices[0].message.content.lower()
    assert resp.choices[0].finish_reason == "content_filter"


def test_rate_limit_maps_to_retryable_error(monkeypatch):
    client = make_client(monkeypatch, status=429)
    with pytest.raises(anthropic.RateLimitError) as exc_info:
        client.chat.completions.create(
            model="claude-sonnet-5",
            messages=[{"role": "user", "content": "hi"}], max_tokens=64)
    # The agent loop's retry heuristic keys on status_code / exception name.
    from ocd_core.agent import _is_retryable
    assert exc_info.value.status_code == 429
    assert _is_retryable(exc_info.value)
