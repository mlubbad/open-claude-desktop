"""Native Anthropic Messages-API adapter (P2).

Every other provider speaks OpenAI-compatible chat completions through one client
shape; Anthropic's native API is the one deliberate exception, because the
compatibility surface can't express its two headline features:

* **Prompt caching** — ``cache_control`` breakpoints on the system prompt and the
  conversation tail make each agent round re-read the whole prefix at ~10% price.
* **Native extended thinking** — real provider-side reasoning (adaptive on modern
  models, budget-based on older ones) streamed into the same "think" scope the UI
  already renders.

Rather than teach the agent loop a second call shape, this module exposes an
OpenAI-compatible facade: ``AnthropicNativeClient().chat.completions.create(...)``
accepts exactly the kwargs the agent loop already sends and yields chunk objects
with the exact attributes it already reads (``choices[0].delta.content`` /
``.reasoning_content`` / ``.tool_calls``, ``usage``). ``llm.get_client`` returns it
for the ``anthropic`` provider and NOTHING else changes — retries, fallback,
artifact streaming, usage metering all keep working.

Model families differ in what the Messages API accepts; requests are shaped
per-model (see ``_family``):

* always-on thinking (never send ``thinking``; sampling params rejected)
* adaptive thinking (``{"type": "adaptive"}`` + ``output_config.effort``;
  sampling params rejected on 4.7+/5-series)
* budget thinking (older models: ``{"type": "enabled", "budget_tokens": N}``,
  which requires dropping ``temperature`` and headroom in ``max_tokens``)

Thinking blocks that precede tool calls must be echoed back on the next round
(they carry signatures). The agent loop stores history as OpenAI-style dicts, so
this module keeps a small in-process cache keyed by tool-call id and re-attaches
the blocks at translation time.
"""
from __future__ import annotations

import json
import re
import threading
import types
from collections import OrderedDict

# --------------------------------------------------------------------------- #
#  Model families
# --------------------------------------------------------------------------- #
# "claude-sonnet-4-5-20250929" / "claude-sonnet-5" style (tier then version)…
_NEW_STYLE = re.compile(r"(opus|sonnet|haiku)[-.](\d{1,2})(?:[-.](\d{1,2}))?(?!\d)")
# …and legacy "claude-3-5-sonnet-20241022" style (version then tier).
_OLD_STYLE = re.compile(r"claude[-.](\d)(?:[-.](\d))?[-.](opus|sonnet|haiku)")


def _tier_version(model: str) -> tuple[str | None, int, int]:
    name = (model or "").lower()
    m = _NEW_STYLE.search(name)
    if m:
        return m.group(1), int(m.group(2)), int(m.group(3) or 0)
    m = _OLD_STYLE.search(name)
    if m:
        return m.group(3), int(m.group(1)), int(m.group(2) or 0)
    return None, 0, 0


def _family(model: str) -> str:
    """"always" (thinking always on, no `thinking` param), "adaptive"
    (`{"type": "adaptive"}`), or "budget" (legacy `budget_tokens` models)."""
    name = (model or "").lower()
    if "fable" in name or "mythos" in name:
        return "always"
    tier, major, minor = _tier_version(name)
    if tier in ("opus", "sonnet") and ((major, minor) >= (4, 6) or major >= 5):
        return "adaptive"
    return "budget"


def _rejects_sampling(model: str) -> bool:
    """Models that 400 on temperature/top_p/top_k (4.7+, 5-series, always-on)."""
    name = (model or "").lower()
    if "fable" in name or "mythos" in name:
        return True
    tier, major, minor = _tier_version(name)
    if tier == "opus" and (major, minor) >= (4, 7):
        return True
    return tier in ("opus", "sonnet", "haiku") and major >= 5


# Legacy budget-based thinking: tokens the model may think with, per effort level.
_BUDGETS = {"low": 2048, "medium": 8192, "high": 16384}


# --------------------------------------------------------------------------- #
#  Thinking-block replay cache
#
#  A thinking block that precedes tool_use blocks is signed and must be sent back
#  verbatim with that assistant turn on the follow-up request. The agent loop's
#  history is OpenAI-shaped (text + tool_calls only), so remember the raw blocks
#  here, keyed by every tool-call id they preceded, and re-attach on translation.
#  In-process and bounded: a tool loop always round-trips within one process.
# --------------------------------------------------------------------------- #
_THINKING_CACHE: OrderedDict[str, list[dict]] = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_MAX = 512


def _remember_thinking(tool_ids: list[str], blocks: list[dict]) -> None:
    if not tool_ids or not blocks:
        return
    with _CACHE_LOCK:
        for tid in tool_ids:
            _THINKING_CACHE[tid] = blocks
            _THINKING_CACHE.move_to_end(tid)
        while len(_THINKING_CACHE) > _CACHE_MAX:
            _THINKING_CACHE.popitem(last=False)


def _recall_thinking(tool_ids: list[str]) -> list[dict]:
    with _CACHE_LOCK:
        for tid in tool_ids:
            if tid in _THINKING_CACHE:
                return _THINKING_CACHE[tid]
    return []


# --------------------------------------------------------------------------- #
#  OpenAI -> Anthropic translation (pure, unit-tested)
# --------------------------------------------------------------------------- #
_DATA_URI = re.compile(r"^data:(image/[a-z+.-]+);base64,(.+)$", re.DOTALL)


def _image_block(url: str) -> dict:
    m = _DATA_URI.match(url or "")
    if m:
        return {"type": "image",
                "source": {"type": "base64", "media_type": m.group(1),
                           "data": m.group(2)}}
    return {"type": "image", "source": {"type": "url", "url": url}}


def _user_blocks(content) -> list[dict]:
    """OpenAI user content (str or multimodal part list) -> Anthropic blocks."""
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    blocks: list[dict] = []
    for part in content or []:
        kind = part.get("type")
        if kind == "text" and part.get("text"):
            blocks.append({"type": "text", "text": part["text"]})
        elif kind == "image_url":
            blocks.append(_image_block((part.get("image_url") or {}).get("url", "")))
    return blocks


def _tool_use_blocks(tool_calls: list) -> list[dict]:
    blocks = []
    for tc in tool_calls or []:
        tc = tc if isinstance(tc, dict) else tc.model_dump()
        fn = tc.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
            if not isinstance(args, dict):
                args = {}
        except ValueError:
            args = {}
        blocks.append({"type": "tool_use", "id": tc.get("id", ""),
                       "name": fn.get("name", ""), "input": args})
    return blocks


def _assistant_blocks(msg: dict, attach_thinking: bool) -> list[dict]:
    """Assistant history message -> Anthropic blocks, re-attaching any remembered
    signed thinking blocks ahead of the tool calls they preceded."""
    blocks: list[dict] = []
    tool_calls = msg.get("tool_calls") or []
    if attach_thinking and tool_calls:
        ids = [tc.get("id", "") if isinstance(tc, dict) else tc.id for tc in tool_calls]
        blocks.extend(_recall_thinking([i for i in ids if i]))
    content = msg.get("content")
    if isinstance(content, str) and content:
        blocks.append({"type": "text", "text": content})
    blocks.extend(_tool_use_blocks(tool_calls))
    return blocks


def to_anthropic_messages(messages: list[dict], *, attach_thinking: bool = True,
                          ) -> tuple[list[dict], list[dict]]:
    """Split an OpenAI-style message list into (system_blocks, anthropic_messages).

    Consecutive same-role turns are merged, and tool results ride as tool_result
    blocks inside a user turn — all results for one assistant turn in a SINGLE
    user message (splitting them degrades parallel tool use)."""
    system_blocks: list[dict] = []
    out: list[dict] = []

    def _append(role: str, blocks: list[dict]):
        if not blocks:
            return
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": blocks})

    for msg in messages or []:
        role = msg.get("role")
        if role == "system":
            text = msg.get("content") or ""
            if text:
                system_blocks.append({"type": "text", "text": text})
        elif role == "user":
            _append("user", _user_blocks(msg.get("content")))
        elif role == "assistant":
            _append("assistant", _assistant_blocks(msg, attach_thinking))
        elif role == "tool":
            content = msg.get("content")
            block = {"type": "tool_result",
                     "tool_use_id": msg.get("tool_call_id", ""),
                     "content": content if isinstance(content, str) else str(content)}
            _append("user", [block])
    return system_blocks, out


def to_anthropic_tools(tools: list[dict] | None) -> list[dict]:
    """OpenAI function-tool specs -> Anthropic tool definitions."""
    out = []
    for t in tools or []:
        fn = t.get("function") or {}
        out.append({"name": fn.get("name", ""),
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters")
                    or {"type": "object", "properties": {}}})
    return out


def apply_cache_control(system_blocks: list[dict], messages: list[dict]) -> None:
    """Place the two prompt-caching breakpoints (of the 4 allowed): the last system
    block (caches tools + system — tools render first) and the last content block
    of the final message (caches the whole conversation prefix, so each agent round
    and each follow-up turn re-reads it at ~10% of input price)."""
    if system_blocks:
        system_blocks[-1]["cache_control"] = {"type": "ephemeral"}
    if messages and messages[-1]["content"]:
        messages[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}


def thinking_params(model: str, reasoning: str | None, max_tokens: int,
                    temperature: float | None, *, thinking_ok: bool = True) -> dict:
    """The per-model-family request shape: thinking/effort config, whether the
    sampling param survives, and the effective max_tokens.

    ``thinking_ok=False`` forces thinking off where possible — used when history
    contains a tool round whose signed thinking blocks we no longer have (budget
    models reject that combination)."""
    family = _family(model)
    kw: dict = {"max_tokens": max_tokens}
    effort = reasoning if reasoning in ("low", "medium", "high") else None

    if family == "always":
        # Thinking cannot be configured off; surface the summarized reasoning so
        # the UI's think scope has something to show.
        kw["thinking"] = {"type": "adaptive", "display": "summarized"}
        if effort:
            kw["output_config"] = {"effort": effort}
    elif family == "adaptive":
        if effort and thinking_ok:
            kw["thinking"] = {"type": "adaptive", "display": "summarized"}
            kw["output_config"] = {"effort": effort}
    else:  # budget (legacy models)
        if effort and thinking_ok:
            budget = _BUDGETS[effort]
            # budget_tokens must be strictly below max_tokens: give the answer the
            # originally requested room ON TOP of the thinking budget.
            kw["thinking"] = {"type": "enabled", "budget_tokens": budget}
            kw["max_tokens"] = max(max_tokens, budget + max_tokens)

    thinking_on = "thinking" in kw or family == "always"
    if temperature is not None and not _rejects_sampling(model) and not thinking_on:
        kw["temperature"] = temperature
    return kw


# --------------------------------------------------------------------------- #
#  OpenAI-shaped response shims (only the attributes the agent loop reads)
# --------------------------------------------------------------------------- #
class _ToolCall:
    """Mirrors an OpenAI tool_call (both the streaming-delta and message shape)."""

    def __init__(self, index: int, id: str = "", name: str = "", arguments: str = ""):
        self.index = index
        self.id = id
        self.type = "function"
        self.function = types.SimpleNamespace(name=name, arguments=arguments)

    def model_dump(self):
        return {"id": self.id, "type": "function",
                "function": {"name": self.function.name,
                             "arguments": self.function.arguments}}


def _usage_ns(input_tokens: int, output_tokens: int, cache_read: int,
              cache_creation: int):
    # prompt_tokens is the REAL total input (uncached + cache reads + cache writes)
    # so the usage meter reports what the provider actually processed.
    return types.SimpleNamespace(
        prompt_tokens=input_tokens + cache_read + cache_creation,
        completion_tokens=output_tokens,
        prompt_tokens_details=types.SimpleNamespace(cached_tokens=cache_read))


def _chunk(*, content=None, reasoning=None, tool_calls=None, usage=None,
           finish_reason=None):
    delta = types.SimpleNamespace(content=content, reasoning_content=reasoning,
                                  tool_calls=tool_calls)
    choice = types.SimpleNamespace(delta=delta, finish_reason=finish_reason)
    has_delta = any(v is not None for v in (content, reasoning, tool_calls,
                                            finish_reason))
    return types.SimpleNamespace(choices=[choice] if has_delta else [],
                                 usage=usage)


_FINISH = {"tool_use": "tool_calls", "max_tokens": "length"}


# --------------------------------------------------------------------------- #
#  The facade
# --------------------------------------------------------------------------- #
class _Completions:
    def __init__(self, client):
        self._client = client  # anthropic.Anthropic

    # The exact call shape agent.py / probe_provider use — extra OpenAI-only params
    # (stream_options, …) are accepted and ignored.
    def create(self, *, model: str, messages: list[dict], stream: bool = False,
               tools: list[dict] | None = None, tool_choice=None,
               temperature: float | None = None, max_tokens: int = 4096,
               reasoning_effort: str | None = None, **_ignored):
        # A budget-family request can only keep thinking if the LAST tool round's
        # signed thinking blocks are still cached (e.g. not after an app restart
        # mid-conversation); adaptive models tolerate their absence.
        thinking_ok = True
        if reasoning_effort and _family(model) == "budget":
            last_tools = next((m.get("tool_calls") for m in reversed(messages or [])
                               if m.get("role") == "assistant" and m.get("tool_calls")),
                              None)
            if last_tools:
                ids = [tc.get("id", "") if isinstance(tc, dict) else tc.id
                       for tc in last_tools]
                thinking_ok = bool(_recall_thinking([i for i in ids if i]))

        system_blocks, anth_messages = to_anthropic_messages(messages)
        apply_cache_control(system_blocks, anth_messages)
        kw = thinking_params(model, reasoning_effort, max_tokens, temperature,
                             thinking_ok=thinking_ok)
        kw["model"] = model
        kw["messages"] = anth_messages
        if system_blocks:
            kw["system"] = system_blocks
        if tools:
            kw["tools"] = to_anthropic_tools(tools)
            kw["tool_choice"] = {"type": "auto"}
        if stream:
            return self._stream(kw)
        return self._complete(kw)

    # ---- non-streaming (probe, fallback path) ---------------------------- #
    def _complete(self, kw: dict):
        msg = self._client.messages.create(**kw)
        text, tool_calls, thinking_blocks = [], [], []
        for block in msg.content or []:
            if block.type == "text":
                text.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(_ToolCall(len(tool_calls), block.id, block.name,
                                            json.dumps(block.input or {})))
            elif block.type in ("thinking", "redacted_thinking"):
                thinking_blocks.append(block.model_dump(exclude_none=True))
        _remember_thinking([tc.id for tc in tool_calls], thinking_blocks)
        u = msg.usage
        usage = _usage_ns(u.input_tokens or 0, u.output_tokens or 0,
                          getattr(u, "cache_read_input_tokens", 0) or 0,
                          getattr(u, "cache_creation_input_tokens", 0) or 0)
        message = types.SimpleNamespace(content="".join(text),
                                        tool_calls=tool_calls or None)
        choice = types.SimpleNamespace(
            message=message, finish_reason=_FINISH.get(msg.stop_reason, "stop"))
        return types.SimpleNamespace(choices=[choice], usage=usage, model=msg.model)

    # ---- streaming (the agent loop's normal path) ------------------------ #
    def _stream(self, kw: dict):
        events = self._client.messages.create(**kw, stream=True)
        blocks: dict[int, dict] = {}   # index -> {"kind", "id"?, "tool_index"?, ...}
        thinking_blocks: list[dict] = []
        tool_ids: list[str] = []
        n_tools = 0
        usage_in = usage_read = usage_write = usage_out = 0
        finish = None

        for ev in events:
            et = ev.type
            if et == "message_start":
                u = ev.message.usage
                usage_in = u.input_tokens or 0
                usage_read = getattr(u, "cache_read_input_tokens", 0) or 0
                usage_write = getattr(u, "cache_creation_input_tokens", 0) or 0
                usage_out = u.output_tokens or 0
            elif et == "content_block_start":
                cb = ev.content_block
                if cb.type == "tool_use":
                    blocks[ev.index] = {"kind": "tool", "tool_index": n_tools}
                    tool_ids.append(cb.id)
                    yield _chunk(tool_calls=[_ToolCall(n_tools, cb.id, cb.name)])
                    n_tools += 1
                elif cb.type == "thinking":
                    blocks[ev.index] = {"kind": "thinking", "type": "thinking",
                                        "thinking": "", "signature": ""}
                elif cb.type == "redacted_thinking":
                    blocks[ev.index] = {"kind": "redacted",
                                        "type": "redacted_thinking",
                                        "data": getattr(cb, "data", "")}
                else:
                    blocks[ev.index] = {"kind": "text"}
            elif et == "content_block_delta":
                d = ev.delta
                acc = blocks.get(ev.index, {})
                if d.type == "text_delta" and d.text:
                    yield _chunk(content=d.text)
                elif d.type == "thinking_delta" and d.thinking:
                    acc["thinking"] = acc.get("thinking", "") + d.thinking
                    yield _chunk(reasoning=d.thinking)
                elif d.type == "signature_delta":
                    acc["signature"] = getattr(d, "signature", "") or ""
                elif d.type == "input_json_delta" and d.partial_json:
                    yield _chunk(tool_calls=[
                        _ToolCall(acc.get("tool_index", 0),
                                  arguments=d.partial_json)])
            elif et == "content_block_stop":
                acc = blocks.get(ev.index, {})
                if acc.get("kind") in ("thinking", "redacted"):
                    raw = {k: v for k, v in acc.items() if k != "kind"}
                    thinking_blocks.append(raw)
            elif et == "message_delta":
                if getattr(ev, "usage", None) is not None:
                    usage_out = ev.usage.output_tokens or usage_out
                stop = getattr(ev.delta, "stop_reason", None)
                if stop:
                    finish = _FINISH.get(stop, "stop")

        _remember_thinking(tool_ids, thinking_blocks)
        yield _chunk(usage=_usage_ns(usage_in, usage_out, usage_read, usage_write),
                     finish_reason=finish)


class AnthropicNativeClient:
    """OpenAI-compatible facade over the native Anthropic Messages API."""

    def __init__(self, api_key: str, base_url: str | None = None):
        import anthropic  # imported here so only the anthropic provider needs it
        self._client = anthropic.Anthropic(api_key=api_key, base_url=base_url)
        self.chat = types.SimpleNamespace(completions=_Completions(self._client))
