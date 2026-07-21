// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RewindMenu } from "./RewindMenu";

describe("RewindMenu", () => {
  it("calls onRestore with the chosen scope", () => {
    const onRestore = vi.fn();
    render(<RewindMenu turnId="t1" onRestore={onRestore} />);
    fireEvent.click(screen.getByText(/restore files/i));
    expect(onRestore).toHaveBeenCalledWith("t1", "files");
  });

  it("does not offer a conversation-restore option (v1 is files-only)", () => {
    render(<RewindMenu turnId="t1" onRestore={() => {}} />);
    expect(screen.queryByText(/conversation/i)).not.toBeInTheDocument();
  });
});
