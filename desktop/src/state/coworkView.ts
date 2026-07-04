// Pure helpers for the Cowork tab. Replays a completed/running task's stored event
// stream through the SAME transcript reducer the live chat uses, so a delegated task
// renders identically to an interactive one — no duplicate rendering logic.

import type { AgentEvent } from "../api/events";
import { applyEvent, initialState, startTurn, type TranscriptState } from "./transcript";

export function replayEvents(goal: string, events: AgentEvent[]): TranscriptState {
  let state = startTurn(initialState(), goal);
  for (const ev of events) state = applyEvent(state, ev);
  return state;
}

// A short status glyph + label for a task's state.
export function statusBadge(status: string): { icon: string; label: string; cls: string } {
  switch (status) {
    case "running":
      return { icon: "◐", label: "running", cls: "running" };
    case "done":
      return { icon: "✓", label: "done", cls: "done" };
    case "error":
      return { icon: "✗", label: "error", cls: "error" };
    case "cancelled":
      return { icon: "⊘", label: "cancelled", cls: "cancelled" };
    default:
      return { icon: "•", label: status, cls: "" };
  }
}

export function hasRunning(tasks: { status: string }[]): boolean {
  return tasks.some((t) => t.status === "running");
}
