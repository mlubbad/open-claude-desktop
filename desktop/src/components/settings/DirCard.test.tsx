// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DirCard, DirEmpty, DirToolbar } from "./DirCard";

describe("DirCard", () => {
  it("renders the title, badges, and body children", () => {
    render(
      <DirCard icon="bulb" title="/hero" badges={<span className="badge-pill">auto</span>}>
        <p className="dir-card-desc">A skill</p>
      </DirCard>,
    );
    expect(screen.getByText("/hero")).toBeInTheDocument();
    expect(screen.getByText("auto")).toBeInTheDocument();
    expect(screen.getByText("A skill")).toBeInTheDocument();
  });

  it("applies an extra className onto the card frame", () => {
    const { container } = render(<DirCard icon="sliders" title="x" className="is-on" />);
    expect(container.querySelector(".dir-card.is-on")).toBeTruthy();
  });

  it("DirEmpty renders its message", () => {
    render(<DirEmpty>No skills yet</DirEmpty>);
    expect(screen.getByText("No skills yet")).toBeInTheDocument();
  });

  it("DirToolbar wires the search input", () => {
    render(<DirToolbar q="abc" onQ={() => {}} placeholder="Search skills…" />);
    expect(screen.getByPlaceholderText("Search skills…")).toHaveValue("abc");
  });
});
