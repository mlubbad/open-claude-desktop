// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { WorkspaceBar } from "./WorkspaceBar";

describe("WorkspaceBar", () => {
  it("shows the folder name and mode selector", () => {
    render(<WorkspaceBar root="C:/proj/demo" mode="acceptEdits" onModeChange={() => {}} onDetach={() => {}} />);
    expect(screen.getByText(/demo/)).toBeInTheDocument();
    expect(screen.getByLabelText(/permission mode/i)).toBeInTheDocument();
  });

  it("reflects the current mode in the selector and calls onModeChange on change", () => {
    const onModeChange = vi.fn();
    render(<WorkspaceBar root="/proj/demo" mode="plan" onModeChange={onModeChange} onDetach={() => {}} />);
    const select = screen.getByLabelText(/permission mode/i) as HTMLSelectElement;
    expect(select.value).toBe("plan");
  });

  it("calls onDetach when the Detach button is clicked", () => {
    const onDetach = vi.fn();
    render(<WorkspaceBar root="/proj/demo" mode="default" onModeChange={() => {}} onDetach={onDetach} />);
    screen.getByText(/detach/i).click();
    expect(onDetach).toHaveBeenCalledTimes(1);
  });
});
