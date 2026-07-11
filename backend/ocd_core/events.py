"""Event-stream helpers shared by consumers of the agent's event contract.

``agent.run_turn`` yields a UI-shaped event stream; several backend consumers need
to reconstruct "the final answer" from it (the subagent runner, the Opik trace tap,
the evaluation harness — the desktop transcript is the unavoidable TS copy). The
fold has a subtle contract, so it lives here ONCE instead of three hand-rolled
copies drifting apart.
"""
from __future__ import annotations


class AnswerAccumulator:
    """Folds a turn's event stream into its FINAL answer text.

    Contract (from the run_turn loop): each ``answer_open`` starts a new answer block
    that SUPERSEDES anything streamed before it, and ``answer_to_think`` demotes the
    current block to narration (it precedes tool rounds) — both reset the fold.
    ``delta`` events with scope="answer" append to the current block. A turn that
    dies after narration with no final block therefore folds to "" for every
    consumer alike.
    """

    def __init__(self) -> None:
        self._parts: list[str] = []

    def feed(self, ev: dict) -> None:
        t = ev.get("type")
        if t in ("answer_open", "answer_to_think"):
            self._parts.clear()
        elif t == "delta" and ev.get("scope") == "answer":
            self._parts.append(ev.get("text", ""))

    @property
    def text(self) -> str:
        return "".join(self._parts)
