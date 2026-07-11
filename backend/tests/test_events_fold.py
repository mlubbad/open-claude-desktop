"""AnswerAccumulator — the single home of the final-answer fold contract.

Three backend consumers (subagent runner, Opik tap, evals harness) used to
hand-roll this fold; they now share this class, so the contract is pinned once.
"""
from ocd_core.events import AnswerAccumulator


def _fold(events):
    acc = AnswerAccumulator()
    for ev in events:
        acc.feed(ev)
    return acc.text


def test_final_block_supersedes_narration():
    assert _fold([
        {"type": "answer_open"},
        {"type": "delta", "scope": "answer", "text": "narration"},
        {"type": "answer_to_think", "phase": "narration"},
        {"type": "tool", "id": "c1", "name": "x"},
        {"type": "answer_open"},
        {"type": "delta", "scope": "answer", "text": "final "},
        {"type": "delta", "scope": "answer", "text": "answer"},
    ]) == "final answer"


def test_think_deltas_are_ignored():
    assert _fold([
        {"type": "think_open", "phase": "plan"},
        {"type": "delta", "scope": "think", "text": "hmm"},
        {"type": "think_close"},
        {"type": "answer_open"},
        {"type": "delta", "scope": "answer", "text": "yes"},
    ]) == "yes"


def test_turn_dying_after_narration_folds_to_empty():
    """answer_to_think demotes the block; with no later answer block the fold is ''
    — the same for every consumer (subagent, trace output, eval output)."""
    assert _fold([
        {"type": "answer_open"},
        {"type": "delta", "scope": "answer", "text": "half an answer"},
        {"type": "answer_to_think", "phase": "narration"},
        {"type": "error", "text": "provider died"},
    ]) == ""
