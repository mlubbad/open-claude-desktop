// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SkillsPage } from "./SkillsPage";
import type { SkillControls } from "./types";

function makeControls(over: Partial<SkillControls> = {}): SkillControls {
  return {
    list: [
      { name: "hero", description: "Hero help", auto: true, triggers: ["hero"], imported: true },
      { name: "bundled", description: "Bundled", imported: false },
    ],
    busy: false,
    allowRemote: true,
    importFile: vi.fn(async () => null),
    importZip: vi.fn(async () => null),
    importFromRepo: vi.fn(async () => null),
    onRemove: vi.fn(),
    ...over,
  };
}

describe("SkillsPage", () => {
  it("renders a card per skill with its /name title", () => {
    render(<SkillsPage c={makeControls()} />);
    expect(screen.getByText("/hero")).toBeInTheDocument();
    expect(screen.getByText("/bundled")).toBeInTheDocument();
  });

  it("offers Remove only for imported skills and calls onRemove", () => {
    const c = makeControls();
    render(<SkillsPage c={c} />);
    expect(screen.queryByLabelText("Remove bundled")).toBeNull(); // bundled is not removable
    fireEvent.click(screen.getByLabelText("Remove hero"));
    expect(c.onRemove).toHaveBeenCalledWith("hero");
  });

  it("filters the grid by the search box", () => {
    render(<SkillsPage c={makeControls()} />);
    fireEvent.change(screen.getByPlaceholderText("Search skills…"), { target: { value: "hero" } });
    expect(screen.getByText("/hero")).toBeInTheDocument();
    expect(screen.queryByText("/bundled")).toBeNull();
  });

  it("shows the empty state when there are no skills", () => {
    render(<SkillsPage c={makeControls({ list: [] })} />);
    expect(screen.getByText(/No skills yet/)).toBeInTheDocument();
  });
});
