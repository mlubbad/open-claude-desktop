// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { FileDiffCard } from "./FileDiffCard";

describe("FileDiffCard", () => {
  it("renders added and removed lines", () => {
    render(<FileDiffCard diff={"--- a\n+++ a\n-old line\n+new line"} />);
    expect(screen.getByText(/new line/)).toBeInTheDocument();
    expect(screen.getByText(/old line/)).toBeInTheDocument();
  });

  it("distinguishes add/del/context lines for styling", () => {
    render(<FileDiffCard diff={"--- a\n+++ a\n+new line\n-old line\n ctx line"} />);
    expect(screen.getByText(/\+new line/).className).toContain("add");
    expect(screen.getByText(/-old line/).className).toContain("del");
  });
});
