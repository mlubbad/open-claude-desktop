// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ImageZoom } from "./ImageZoom";

const SRC = "data:image/png;base64,iVBORw0KGgo=";

describe("ImageZoom", () => {
  it("opens a full-size lightbox on click and closes on Escape", () => {
    render(<ImageZoom src={SRC} alt="chart" className="attach-thumb" />);
    expect(screen.queryByRole("dialog")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "chart" }));
    const dialog = screen.getByRole("dialog", { name: "chart" });
    expect(dialog).toBeInTheDocument();
    // The enlarged image is present (thumbnail + lightbox both render the src).
    expect(screen.getAllByAltText("chart").length).toBeGreaterThan(1);

    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes when the backdrop is clicked", () => {
    render(<ImageZoom src={SRC} alt="pic" />);
    fireEvent.click(screen.getByRole("button", { name: "pic" }));
    fireEvent.click(screen.getByRole("dialog", { name: "pic" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
