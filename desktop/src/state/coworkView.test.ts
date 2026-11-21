import { describe, expect, it } from "vitest";

import type { AgentEvent } from "../api/events";
import { hasRunning, nextRun, nextRunLabel, relativeTime, replayEvents, statusBadge } from "./coworkView";

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

describe("relativeTime", () => {
  const now = Date.parse("2026-07-12T12:00:00Z");
  it("humanizes recent-to-old timestamps", () => {
    expect(relativeTime("2026-07-12T11:59:50Z", now)).toBe("just now");
    expect(relativeTime("2026-07-12T11:58:00Z", now)).toBe("2 minutes ago");
    expect(relativeTime("2026-07-12T09:00:00Z", now)).toBe("3 hours ago");
    expect(relativeTime("2026-07-11T12:00:00Z", now)).toBe("yesterday");
    expect(relativeTime("2026-07-09T12:00:00Z", now)).toBe("3 days ago");
    expect(relativeTime("not-a-date", now)).toBe("");
  });
});

describe("nextRun / nextRunLabel", () => {
  const now = Date.parse("2026-07-12T12:00:00Z");
  it("interval counts from last_run and skips missed fires", () => {
    const soon = nextRun({ kind: "interval", every_seconds: 3600, last_run: "2026-07-12T11:30:00Z", enabled: true }, now);
    expect(soon?.toISOString()).toBe("2026-07-12T12:30:00.000Z");
    // A long-overdue interval schedules the NEXT fire from now, not a past instant.
    const overdue = nextRun({ kind: "interval", every_seconds: 3600, last_run: "2026-07-01T00:00:00Z", enabled: true }, now);
    expect(overdue!.getTime()).toBeGreaterThan(now);
  });
  it("daily uses the next HH:MM UTC occurrence", () => {
    const later = nextRun({ kind: "daily", at: "18:00", enabled: true }, now);
    expect(later?.toISOString()).toBe("2026-07-12T18:00:00.000Z");
    const tomorrow = nextRun({ kind: "daily", at: "06:00", enabled: true }, now);
    expect(tomorrow?.toISOString()).toBe("2026-07-13T06:00:00.000Z");
  });
  it("a disabled schedule has no next run", () => {
    expect(nextRun({ kind: "daily", at: "06:00", enabled: false }, now)).toBeNull();
    expect(nextRunLabel(null)).toBe("paused");
  });
});

describe("statusBadge interrupted", () => {
  it("maps interrupted to an error-styled paused badge", () => {
    expect(statusBadge("interrupted").label).toBe("interrupted");
    expect(statusBadge("interrupted").cls).toBe("error");
  });
});
