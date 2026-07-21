// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PlanCard } from "./PlanCard";

describe("PlanCard", () => {
  it("renders items with status", () => {
    render(
      <PlanCard
        items={[
          { id: 1, subject: "read code", status: "completed" },
          { id: 2, subject: "write test", status: "in_progress" },
        ]}
      />,
    );
    expect(screen.getByText("read code")).toBeInTheDocument();
    expect(screen.getByText("write test")).toBeInTheDocument();
  });

  it("marks each item's status via a data attribute for styling", () => {
    render(<PlanCard items={[{ id: 1, subject: "plan it", status: "pending" }]} />);
    expect(screen.getByText("plan it").closest("li")).toHaveAttribute("data-status", "pending");
  });
});
