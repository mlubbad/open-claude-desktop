"""Offline evaluation harness — regression-test the agent against a golden dataset
and register the experiment on Opik (CI/CD quality gate).

Usage (requires the optional extra + a reachable Opik instance + a configured
model provider):

    pip install -e backend[observability]
    # self-hosted Opik:  git clone https://github.com/comet-ml/opik && ./opik.sh
    export OPIK_URL_OVERRIDE="http://localhost:5173/api/"   # or Opik Cloud + OPIK_API_KEY
    python backend/evals/run_evaluations.py [--experiment NAME] [--threshold 0.6]

For every item in evals/golden.jsonl the harness runs a real agent turn through
``ocd_core.agent.run_turn`` (whatever model/provider is configured in settings),
scores it with:

  * LevenshteinRatio — the edit-distance guardrail D_L(a,b) = 1 - dist/max(|a|,|b|)
    against the golden reference,
  * ToolExecutionQuality — a custom heuristic metric that inspects the turn's TOOL
    events for failures (agentic runs must be judged on their traces, not only
    their final text),

and exits non-zero when the mean LevenshteinRatio falls below --threshold, so a
CI pipeline can block prompt/model changes that regress quality.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # backend/ on sys.path

from ocd_core import agent, opik_tracing, settings  # noqa: E402

GOLDEN = Path(__file__).with_name("golden.jsonl")


def run_agent_turn(goal: str) -> dict[str, Any]:
    """One full (non-streamed) agent turn: returns the final answer text + the raw
    tool events, so metrics can judge the trace as well as the text."""
    answer: list[str] = []
    tool_events: list[dict] = []

    async def _drive() -> None:
        async for ev in agent.run_turn(goal, [], None, settings.get_settings()["model"],
                                       effort="Low", permission_mode="auto"):
            t = ev.get("type")
            if t in ("answer_open", "answer_to_think"):
                answer.clear()
            elif t == "delta" and ev.get("scope") == "answer":
                answer.append(ev.get("text", ""))
            elif t in ("tool", "tool_result", "tool_error"):
                tool_events.append(ev)

    asyncio.run(_drive())
    return {"output": "".join(answer).strip(), "tool_events": tool_events}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--experiment", default="agent-regression")
    ap.add_argument("--threshold", type=float, default=0.6,
                    help="minimum mean LevenshteinRatio to pass (CI gate)")
    ap.add_argument("--samples", type=int, default=None, help="limit dataset items")
    args = ap.parse_args()

    try:
        from opik import Opik
        from opik.evaluation import evaluate
        from opik.evaluation.metrics import LevenshteinRatio, base_metric, score_result
    except ImportError:
        print("opik is not installed — run: pip install -e backend[observability]")
        return 2

    class ToolExecutionQuality(base_metric.BaseMetric):
        """Fraction of tool calls that completed without a tool_error event."""

        def __init__(self, name: str = "tool_execution_quality"):
            super().__init__(name)

        def score(self, tool_events: list | None = None,
                  **ignored: Any) -> score_result.ScoreResult:
            events = tool_events or []
            calls = [e for e in events if e.get("type") == "tool"]
            errors = [e for e in events if e.get("type") == "tool_error"]
            if not calls:
                return score_result.ScoreResult(name=self.name, value=1.0,
                                                reason="No tool calls made.")
            value = max(0.0, 1.0 - len(errors) / len(calls))
            return score_result.ScoreResult(
                name=self.name, value=value,
                reason=f"{len(calls)} tool calls, {len(errors)} failed.")

    client = Opik()
    dataset = client.get_or_create_dataset(
        name="agent-golden-dataset",
        description="Regression benchmark for the agent's core behaviors.")
    items = [json.loads(line) for line in GOLDEN.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    dataset.insert(items)  # de-duplicated by content hash on the Opik side

    def task(item: dict[str, Any]) -> dict[str, Any]:
        run = run_agent_turn(item["input"])
        return {"input": item["input"], "output": run["output"],
                "reference": item["expected_output"],
                "tool_events": run["tool_events"]}

    print(f"🚀 Evaluating {args.samples or len(items)} golden items…")
    result = evaluate(
        dataset=dataset,
        task=task,
        scoring_metrics=[LevenshteinRatio(), ToolExecutionQuality()],
        experiment_name=args.experiment,
        nb_samples=args.samples,
    )
    opik_tracing.flush()

    per_metric: dict[str, list[float]] = {}
    for test_result in result.test_results:
        for s in test_result.score_results:
            per_metric.setdefault(s.name, []).append(s.value)
    means = {k: sum(v) / len(v) for k, v in per_metric.items() if v}
    print("🎉 Evaluation complete. Mean scores:", json.dumps(means, indent=2))

    gate = means.get("levenshtein_ratio_metric") or means.get("LevenshteinRatio") or 0.0
    if gate < args.threshold:
        print(f"❌ Regression gate FAILED: {gate:.3f} < {args.threshold}")
        return 1
    print(f"✅ Regression gate passed: {gate:.3f} >= {args.threshold}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
