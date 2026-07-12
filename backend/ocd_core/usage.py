"""Token-usage + cost estimation for the context/cost meter.

Deliberately dependency-free and offline: a heuristic token estimate (~4 chars per
token — the widely-used rule of thumb) rather than a network-fetched BPE vocab, so it
works for any provider and in a packaged desktop app with no connectivity. Accurate
enough to drive a "context is X% full" meter and a rough cost figure; providers that
report exact usage can refine it later.
"""
from __future__ import annotations

import json


def estimate_text(text: str | None) -> int:
    """Approximate token count for a string (~4 chars/token)."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def estimate_messages(messages: list[dict]) -> int:
    """Approximate tokens for a chat message list (content + tool-call args + overhead)."""
    total = 0
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            total += estimate_text(content)
        total += 4  # per-message role/formatting overhead
        for tc in (m.get("tool_calls") or []):
            total += estimate_text(json.dumps(tc, default=str))
    return total


# Approximate public list prices, USD per 1M tokens (input, output). Informational and
# best-effort — matched by substring on the bare model name; unknown models -> no cost.
PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5": (1.25, 10.00),
    "o3-mini": (1.10, 4.40),
    "claude-opus": (5.00, 25.00),
    "claude-sonnet": (3.00, 15.00),
    "claude-haiku": (1.00, 5.00),
    "deepseek-reasoner": (0.55, 2.19),
    "deepseek-chat": (0.27, 1.10),
    "glm-4-plus": (0.60, 0.60),
    "glm-4-flash": (0.01, 0.01),
    "glm-4": (0.10, 0.10),
    "qwen-max": (1.60, 6.40),
    "llama-3.3": (0.20, 0.20),
    "mistral-large": (2.00, 6.00),
}


def price_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    name = (model or "").split("/")[-1].strip().lower()
    for key, (pin, pout) in PRICES.items():
        if key in name:
            return round(input_tokens / 1_000_000 * pin + output_tokens / 1_000_000 * pout, 6)
    return None


def build_usage(model: str, messages: list[dict], output_text: str,
                reported: dict | None = None) -> dict:
    """A `usage` event: context fill (for the meter) + output tokens + cost.

    ``reported`` (optional) carries the PROVIDER's own numbers, folded across every
    LLM round of the turn: {"input": billed prompt tokens (sum), "output": completion
    tokens (sum), "last_prompt": final round's prompt tokens}. When present it
    replaces the ~4-chars/token heuristic — the meter shows the real final context
    size and the cost reflects every round actually billed, not just the last."""
    from .llm import catalog

    limit = catalog.context_window(model)
    if reported and (reported.get("input") or reported.get("output")):
        context_tokens = reported.get("last_prompt") or estimate_messages(messages)
        output_tokens = reported.get("output", 0)
        cost = price_usd(model, reported.get("input", 0), output_tokens)
        source = "reported"
    else:
        context_tokens = estimate_messages(messages)
        output_tokens = estimate_text(output_text)
        cost = price_usd(model, context_tokens, output_tokens)
        source = "estimated"
    pct = min(100, round(context_tokens / limit * 100)) if limit else 0
    return {
        "type": "usage",
        "model": model,
        "context_tokens": context_tokens,
        "output_tokens": output_tokens,
        "context_limit": limit,
        "context_pct": pct,
        "cost_usd": cost,
        "source": source,
    }
