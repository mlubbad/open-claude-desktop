// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ToolTimeline } from "./ToolTimeline";

describe("ToolTimeline", () => {
  it("lists tool calls with status", () => {
    render(<ToolTimeline calls={[{ id: "c1", name: "read_file", ok: true }]} />);
    expect(screen.getByText(/read_file/)).toBeInTheDocument();
  });

  it("marks a failed call distinctly from a successful one", () => {
    render(
      <ToolTimeline
        calls={[
          { id: "c1", name: "read_file", ok: true },
          { id: "c2", name: "edit_file", ok: false },
        ]}
      />,
    );
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveAttribute("data-ok", "true");
    expect(items[1]).toHaveAttribute("data-ok", "false");
  });
});
