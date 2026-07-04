"""Pure terminal renderer for the agent event stream.

Turns each event dict (the frozen vocabulary emitted by ``agent.run_turn``) into the
incremental text to write to the terminal. Kept pure — ``feed`` returns a string and
never touches stdout — so the whole render layer is unit-testable without a TTY. Colour
is applied via ANSI codes only when enabled (a real terminal); disable it for pipes and
tests. A separate ``json_line`` emits the raw event as JSONL for ``--json`` mode.
"""
from __future__ import annotations

import json

RESET = "\x1b[0m"
DIM = "\x1b[2m"
BOLD = "\x1b[1m"
CYAN = "\x1b[36m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
RED = "\x1b[31m"
BLUE = "\x1b[34m"


def json_line(ev: dict) -> str:
    """One JSONL record for --json mode."""
    return json.dumps(ev, default=str) + "\n"


class Renderer:
    """Stateful, incremental renderer. Feed events in order; write the returned text."""

    def __init__(self, color: bool = True) -> None:
        self.color = color
        self._in_answer = False  # whether we're mid answer-stream (for newline hygiene)

    def _c(self, text: str, code: str) -> str:
        return f"{code}{text}{RESET}" if self.color else text

    def feed(self, ev: dict) -> str:
        t = ev.get("type")
        if t == "delta":
            scope = ev.get("scope")
            text = ev.get("text", "")
            if scope == "think":
                return self._c(text, DIM)
            self._in_answer = True
            return text
        if t == "think_open":
            return self._c(f"\n{ev.get('phase', 'thinking')}… ", DIM)
        if t == "think_close":
            return "\n"
        if t == "answer_open":
            return "\n" if not self._in_answer else ""
        if t == "answer_to_think":
            return self._c("\n", DIM)
        if t == "tool":
            head = f"\n{self._c('⚙', CYAN)} {self._c(ev.get('name', 'tool'), BOLD)}"
            inp = (ev.get("input") or "").strip()
            if inp:
                head += " " + self._c(inp.splitlines()[0][:120], DIM)
            return head + "\n"
        if t == "tool_result":
            s = (ev.get("summary") or "").strip()
            return self._c(f"  ✓ {s}\n", GREEN) if s else ""
        if t == "tool_error":
            return self._c(f"  ✗ {ev.get('text', 'tool failed')}\n", RED)
        if t == "table":
            return self._table(ev)
        if t == "sources":
            return self._sources(ev)
        if t == "artifact_open":
            title = ev.get("title") or "artifact"
            kind = ev.get("kind") or ""
            label = f"{title} [{kind}]" if kind else title
            return self._c(f"\n📄 {label}\n", BLUE)
        if t == "artifact_delta":
            return self._c(ev.get("text", ""), DIM)
        if t == "artifact_close":
            return self._c(f"\n  (artifact v{ev.get('version', 1)})\n", DIM)
        if t == "approval_required":
            return self._c(f"\n⚠ approval required: {ev.get('name')} {ev.get('input', '')}\n", YELLOW)
        if t == "usage":
            return self._usage(ev)
        if t == "error":
            return self._c(f"\n✗ {ev.get('text', 'error')}\n", RED)
        return ""  # turn_start, done, unknown → nothing to print

    def _usage(self, ev: dict) -> str:
        parts = []
        if ev.get("output_tokens") is not None:
            parts.append(f"{ev['output_tokens']:,} out")
        if ev.get("context_tokens") is not None:
            parts.append(f"{ev['context_tokens']:,}/{ev.get('context_limit', 0):,} ctx")
        cost = ev.get("cost_usd")
        if cost:
            parts.append(f"${cost:.4f}")
        return self._c(f"\n· {' · '.join(parts)}\n", DIM) if parts else ""

    def _sources(self, ev: dict) -> str:
        items = ev.get("items") or []
        if not items:
            return ""
        lines = [self._c("  sources:", DIM)]
        for s in items[:8]:
            title = s.get("title") or s.get("domain") or s.get("url", "")
            lines.append(self._c(f"   • {title} — {s.get('url', '')}", DIM))
        return "\n".join(lines) + "\n"

    def _table(self, ev: dict) -> str:
        cols = ev.get("columns") or []
        rows = ev.get("rows") or []
        if not cols:
            return ""
        widths = [len(str(c)) for c in cols]
        shown = rows[:20]
        for r in shown:
            for i, c in enumerate(cols):
                widths[i] = max(widths[i], len(str(r.get(c, ""))))
        widths = [min(w, 40) for w in widths]

        def fmt(vals):
            return " │ ".join(str(v)[:widths[i]].ljust(widths[i]) for i, v in enumerate(vals))

        out = ["", "  " + fmt(cols), "  " + "─┼─".join("─" * w for w in widths)]
        out += ["  " + fmt([r.get(c, "") for c in cols]) for r in shown]
        if ev.get("total", len(rows)) > len(shown):
            out.append(self._c(f"  … {ev['total']:,} rows total", DIM))
        return "\n".join(out) + "\n"
