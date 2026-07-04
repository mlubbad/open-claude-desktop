"""Long-horizon context compaction: budgeting, tail preservation, summary insertion,
and the model-window convenience wrapper."""
from ocd_core import context, usage


def _turns(n: int, chars: int = 400) -> list[dict]:
    """n alternating user/assistant turns, each ~chars long."""
    out = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        out.append({"role": role, "content": f"m{i} " + ("x" * chars), "kind": "final"})
    return out


def test_short_history_is_returned_unchanged():
    h = _turns(4, chars=40)
    out, dropped = context.compact_history(h, budget_tokens=100_000)
    assert out == h
    assert dropped == 0


def test_overflowing_history_is_compacted_within_budget():
    h = _turns(40, chars=400)  # ~4000+ tokens
    budget = 800
    out, dropped = context.compact_history(h, budget_tokens=budget)
    assert dropped > 0
    # A single summary note replaces the dropped older turns.
    assert out[0]["kind"] == "compacted"
    assert "compacted" in out[0]["content"].lower()
    # The result fits the budget.
    assert usage.estimate_messages(out) <= budget
    # Total messages = 1 summary + kept tail.
    assert len(out) == 1 + (len(h) - dropped)


def test_most_recent_turn_is_always_preserved():
    h = _turns(30, chars=400)
    out, dropped = context.compact_history(h, budget_tokens=700)
    assert dropped > 0
    # The very last original message survives verbatim as the final kept message.
    assert out[-1] == h[-1]


def test_summary_recaps_earlier_user_topics():
    h = [
        {"role": "user", "content": "Tell me about the Roman aqueducts", "kind": "user"},
        {"role": "assistant", "content": "y" * 4000, "kind": "final"},
        {"role": "user", "content": "and the Colosseum please", "kind": "user"},
        {"role": "assistant", "content": "z" * 4000, "kind": "final"},
        {"role": "user", "content": "latest question", "kind": "user"},
    ]
    out, dropped = context.compact_history(h, budget_tokens=1200)
    assert dropped > 0
    summary = out[0]["content"]
    # Extractive recap favors the user's earlier words.
    assert "aqueducts" in summary or "Colosseum" in summary


def test_empty_history():
    out, dropped = context.compact_history([], budget_tokens=1000)
    assert out == [] and dropped == 0


def test_history_budget_scales_with_context_window():
    # A large-window model gets a larger history budget than a small-window one.
    big = context.history_budget("gpt-4o")        # 128k window
    small = context.history_budget("some-unknown-tiny-model")  # default 8k window
    assert big > small
    assert small >= context.MIN_HISTORY_TOKENS


def test_compact_for_model_uses_the_models_window():
    h = _turns(60, chars=400)
    out, dropped = context.compact_for_model(h, "glm-4-flash")
    # Something was kept, and if compacted the summary note leads.
    assert len(out) >= 1
    if dropped:
        assert out[0]["kind"] == "compacted"
        assert usage.estimate_messages(out) <= context.history_budget("glm-4-flash")


def test_single_giant_message_is_not_dropped_to_nothing():
    # One message bigger than the budget can't be trimmed away; return it as-is.
    h = [{"role": "user", "content": "q" * 40_000, "kind": "user"}]
    out, dropped = context.compact_history(h, budget_tokens=500)
    assert out == h and dropped == 0


def test_truncate_tool_result_passes_through_short_text():
    assert context.truncate_tool_result("small") == "small"
    assert context.truncate_tool_result("") == ""


def test_truncate_tool_result_caps_and_keeps_head_and_tail():
    text = "HEAD" + ("x" * 20_000) + "TAIL"
    out = context.truncate_tool_result(text, max_chars=2000)
    assert len(out) <= 2000
    assert out.startswith("HEAD")  # head preserved
    assert out.endswith("TAIL")  # tail preserved
    assert "truncated to fit the context window" in out


def test_truncate_tool_result_reports_omitted_count():
    text = "a" * 10_000
    out = context.truncate_tool_result(text, max_chars=1000)
    # The notice states how many characters were dropped (kept ≈ 920).
    import re
    m = re.search(r"\[([\d,]+) characters truncated", out)
    assert m
    omitted = int(m.group(1).replace(",", ""))
    assert 9000 < omitted < 10_000
