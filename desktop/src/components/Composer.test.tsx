// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Composer } from "./Composer";

vi.mock("../api/client", () => ({
  mcp: { getPrompt: vi.fn() },
  providers: { list: vi.fn(async () => []) },
  settings: { get: vi.fn(async () => ({})) },
}));

const modelControl = {
  provider: "nim",
  model: "models/gemini-3.1-pro-preview-customtools",
  effort: "High",
  thinking: false,
  onSelectModel: vi.fn(),
  onSelectEffort: vi.fn(),
  onToggleThinking: vi.fn(),
  onMoreModels: vi.fn(),
};

describe("Composer — model pill at narrow widths", () => {
  it("shows the short model label, keeps the full id on the tooltip", () => {
    render(<Composer busy={false} onSend={vi.fn()} onStop={vi.fn()} modelControl={modelControl} />);
    const pill = screen.getByRole("button", { name: /gemini-3\.1-pro-preview-customtools/ });
    // Long ids render their last path segment in a truncating span; the full id
    // stays reachable on hover (the CSS ellipsis contract lives in styles.css).
    expect(pill.title).toBe("models/gemini-3.1-pro-preview-customtools");
    expect(pill.querySelector(".model-name")?.textContent).toBe(
      "gemini-3.1-pro-preview-customtools",
    );
  });

  it("groups the trailing controls so they wrap as one unit", () => {
    const { container } = render(
      <Composer busy={false} onSend={vi.fn()} onStop={vi.fn()} modelControl={modelControl} />,
    );
    const actions = container.querySelector(".composer-row .composer-actions");
    expect(actions).not.toBeNull();
    // Model pill and send button live inside the group; the group is what wraps.
    expect(actions?.querySelector(".composer-pill.model")).not.toBeNull();
    expect(actions?.querySelector(".composer-send")).not.toBeNull();
  });
});
