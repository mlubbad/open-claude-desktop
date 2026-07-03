"""Long-horizon context management.

Keeps a conversation within a model's context window without losing the thread. When
prior turns would overflow the budget, the oldest ones are dropped and replaced by a
single compact summary note, while the most recent turns are preserved verbatim (recent
context matters most for the next reply). Deterministic + dependency-free (extractive
summary, ~4-chars/token estimate) so it is fully unit-testable and safe to run offline in
the packaged app — no extra LLM round-trip on the hot path.
"""
from __future__ import annotations

from . import llm, usage

# Fraction of the context window we allow the *history* to occupy. The rest is reserved
# for the system prompt, the current user goal, tool schemas, and the model's response.
HISTORY_BUDGET_FRACTION = 0.5
# Hard floor so tiny/unknown context windows still leave usable room for a reply.
MIN_HISTORY_TOKENS = 1000


def history_budget(model: str, fraction: float = HISTORY_BUDGET_FRACTION) -> int:
    """Token budget allotted to prior turns for a given model's context window."""
    window = llm.catalog.context_window(model)
    return max(MIN_HISTORY_TOKENS, int(window * fraction))


def _summarize_dropped(dropped: list[dict], max_chars: int = 600) -> str:
    """A short extractive recap of the messages being compacted away. Favors the user's
    own words (what the conversation was about) over assistant prose."""
    users = [m for m in dropped if m.get("role") == "user"]
    picks = users or dropped
    bits: list[str] = []
    for m in picks:
        text = " ".join(str(m.get("content") or "").split())
        if text:
            bits.append(text)
    joined = " · ".join(bits)
    if len(joined) > max_chars:
        joined = joined[:max_chars].rstrip() + "…"
    return joined


def _summary_message(dropped: list[dict]) -> dict:
    """The synthetic note that stands in for the dropped older turns."""
    recap = _summarize_dropped(dropped)
    body = (f"[Earlier conversation compacted to fit the context window — "
            f"{len(dropped)} earlier message(s) omitted.]")
    if recap:
        body += f"\nEarlier topics: {recap}"
    return {"role": "user", "content": body, "kind": "compacted"}


def compact_history(history: list[dict], budget_tokens: int) -> tuple[list[dict], int]:
    """Fit ``history`` within ``budget_tokens``.

    Returns ``(compacted, dropped_count)``. If the history already fits, it is returned
    unchanged with 0 dropped. Otherwise the newest turns are kept (as many as the budget
    allows, always at least one), older turns are dropped, and a single summary note is
    prepended describing what was omitted. History is assumed to be plain role/content
    turns (no tool-call/tool-result pairs to keep intact).
    """
    history = list(history)
    if not history or usage.estimate_messages(history) <= budget_tokens:
        return history, 0

    # Reserve a slice of the budget for the summary note itself.
    reserve = min(300, max(0, budget_tokens // 4))
    keep_budget = max(0, budget_tokens - reserve)

    # Grow the kept tail from the newest message backward while it fits.
    kept: list[dict] = []
    used = 0
    for m in reversed(history):
        cost = usage.estimate_messages([m])
        if kept and used + cost > keep_budget:
            break
        kept.append(m)
        used += cost
    kept.reverse()

    dropped = history[: len(history) - len(kept)]
    if not dropped:
        return history, 0  # nothing actually removable (single huge message)
    return [_summary_message(dropped), *kept], len(dropped)


def compact_for_model(history: list[dict], model: str) -> tuple[list[dict], int]:
    """Convenience: compact prior turns to fit ``model``'s history budget."""
    return compact_history(history, history_budget(model))
