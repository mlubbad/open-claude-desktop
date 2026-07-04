import { describe, expect, it } from "vitest";

import type { AgentEvent } from "../api/events";
import { hasRunning, replayEvents, statusBadge } from "./coworkView";

describe("replayEvents", () => {
  it("rebuilds a transcript from a task's stored events", () => {
    const events: AgentEvent[] = [
      { type: "answer_open" },
      { type: "delta", scope: "answer", text: "Done: " },
      { type: "delta", scope: "answer", text: "42 files." },
      { type: "done" },
    ];
    const state = replayEvents("count files", events);
    // First message is the delegated goal (user), then the assistant answer.
    expect(state.messages[0]).toEqual({ role: "user", text: "count files" });
    const assistant = state.messages.find((m) => m.role === "assistant");
    expect(assistant).toBeTruthy();
    if (assistant && assistant.role === "assistant") {
      const answer = assistant.blocks.find((b) => b.kind === "answer");
      expect(answer && answer.kind === "answer" && answer.text).toBe("Done: 42 files.");
    }
  });

  it("handles an empty event list (just the goal)", () => {
    const state = replayEvents("hi", []);
    expect(state.messages[0]).toEqual({ role: "user", text: "hi" });
  });
});

describe("statusBadge", () => {
  it("maps each status", () => {
    expect(statusBadge("running").label).toBe("running");
    expect(statusBadge("done").icon).toBe("✓");
    expect(statusBadge("error").cls).toBe("error");
    expect(statusBadge("cancelled").label).toBe("cancelled");
  });
});

describe("hasRunning", () => {
  it("detects an in-flight task", () => {
    expect(hasRunning([{ status: "done" }, { status: "running" }])).toBe(true);
    expect(hasRunning([{ status: "done" }, { status: "error" }])).toBe(false);
    expect(hasRunning([])).toBe(false);
  });
});
