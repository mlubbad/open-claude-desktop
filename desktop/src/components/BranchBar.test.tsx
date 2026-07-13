// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BranchFamily } from "../api/client";
import { BranchBar } from "./BranchBar";

const family: BranchFamily = {
  root: "root",
  current: "b1",
  nodes: [
    // Given out of order on purpose: the bar must still lead with the root.
    { id: "b1", title: "Idea", parent_id: "root", fork_index: 1, updated_at: "2026-07-13T01:00:00", project_id: "general" },
    { id: "root", title: "Idea", parent_id: null, fork_index: null, updated_at: "2026-07-13T00:00:00", project_id: "general" },
  ],
};

describe("BranchBar", () => {
  it("renders a chip per family member with the root first, main/fork labels, count", () => {
    render(<BranchBar family={family} current="b1" onSwitch={() => {}} />);
    expect(screen.getByText("2 branches")).toBeInTheDocument();
    const chips = screen.getAllByRole("button");
    expect(chips).toHaveLength(2);
    expect(chips[0]).toHaveTextContent("main"); // root leads regardless of input order
    expect(chips[1]).toHaveTextContent("fork @ 2"); // fork_index 1 → 1-based message 2
  });

  it("marks the active branch inert and switches on clicking another", () => {
    const onSwitch = vi.fn();
    render(<BranchBar family={family} current="b1" onSwitch={onSwitch} />);
    const active = screen.getByRole("button", { name: /fork @ 2/i }); // b1 is current
    expect(active).toHaveAttribute("aria-current", "true");
    expect(active).toBeDisabled();
    fireEvent.click(active);
    expect(onSwitch).not.toHaveBeenCalled(); // clicking the current one does nothing

    fireEvent.click(screen.getByRole("button", { name: /main/i })); // the root
    expect(onSwitch).toHaveBeenCalledWith("root", "general");
  });
});
