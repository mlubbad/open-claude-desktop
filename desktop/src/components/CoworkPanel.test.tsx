// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { CoworkDetail, CoworkTask } from "../api/client";
import { CoworkPanel, type SchedControls } from "./CoworkPanel";

const sched: SchedControls = { items: [], err: null, add: vi.fn(), remove: vi.fn(), toggle: vi.fn() };

function panel(over: Partial<React.ComponentProps<typeof CoworkPanel>> = {}) {
  const props: React.ComponentProps<typeof CoworkPanel> = {
    tasks: [],
    selected: null,
    err: null,
    sched,
    projectName: "General",
    onStart: vi.fn(),
    onOpen: vi.fn(),
    onBack: vi.fn(),
    onCancel: vi.fn(),
    onClear: vi.fn(),
    onResolveApproval: vi.fn(),
    ...over,
  };
  render(<CoworkPanel {...props} />);
  return props;
}

const task = (over: Partial<CoworkTask> = {}): CoworkTask => ({
  id: "t1", title: "Nightly report", status: "done", approval: "skip",
  created_at: "2026-07-12T10:00:00Z", updated_at: "2026-07-12T10:00:00Z", events: 3, ...over,
});

describe("CoworkPanel home", () => {
  it("delegates with the chosen approval mode (Manual default, switch to Skip)", () => {
    const p = panel();
    fireEvent.change(screen.getByPlaceholderText("What should we work on?"), {
      target: { value: "summarize the repo" },
    });
    // Default approval is Manual.
    fireEvent.click(screen.getByTitle("Approvals for this task"));
    fireEvent.click(screen.getByRole("menuitemradio", { name: /Skip/ }));
    fireEvent.click(screen.getByRole("button", { name: "Delegate" }));
    expect(p.onStart).toHaveBeenCalledWith("summarize the repo", "skip");
  });

  it("opens a task on row click and shows Clear active when a task is finished", () => {
    const p = panel({ tasks: [task()] });
    expect(screen.getByText("Nightly report")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Nightly report"));
    expect(p.onOpen).toHaveBeenCalledWith("t1");
    fireEvent.click(screen.getByRole("button", { name: "Clear active" }));
    expect(p.onClear).toHaveBeenCalled();
  });
});

describe("CoworkPanel review", () => {
  const detail: CoworkDetail = {
    ...task({ status: "running", approval: "manual" }),
    goal: "build a chart",
    error: null,
    turn_id: "turn-123",
    answer: "",
    event_list: [
      { type: "answer_open" },
      { type: "tool", id: "c1", name: "bash", input: "rm -rf /", label_running: "Running", label_done: "Ran", icon: "terminal" },
      { type: "approval_required", id: "c1", turn_id: "turn-123", name: "bash", input: "rm -rf /" },
    ],
    files: [{ name: "chart.png", kind: "file" }],
    progress: [
      { label: "Planning the approach", done: true },
      { label: "Verifying the result", done: false },
    ],
  };

  it("renders the right rail (progress, files, context) and resolves a manual approval", () => {
    const p = panel({ selected: detail });
    // Progress checklist from backend-derived steps.
    expect(screen.getByText("Planning the approach")).toBeInTheDocument();
    // Workspace files card.
    expect(screen.getByText("chart.png")).toBeInTheDocument();
    // Context shows approvals mode.
    expect(screen.getByText(/Approvals: Manual/)).toBeInTheDocument();
    // The pending approval is actionable and posts through the shared endpoint.
    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(p.onResolveApproval).toHaveBeenCalledWith("turn-123", "c1", "approve");
  });
});
