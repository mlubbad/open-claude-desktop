// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Composer, type WorkspaceControlInfo } from "./Composer";

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

function baseProps() {
  return { busy: false, onSend: vi.fn(), onStop: vi.fn(), modelControl };
}

describe("Composer workspace wiring", () => {
  it("renders nothing workspace-related when no workspace prop is given", () => {
    render(<Composer {...baseProps()} />);
    expect(screen.queryByLabelText(/permission mode/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/attach folder/i)).not.toBeInTheDocument();
  });

  it("shows the WorkspaceBar when a workspace is attached", () => {
    const workspace: WorkspaceControlInfo = {
      current: { root: "C:/proj/demo", mode: "acceptEdits" },
      onAttach: vi.fn(),
      onModeChange: vi.fn(),
      onDetach: vi.fn(),
    };
    render(<Composer {...baseProps()} workspace={workspace} />);
    expect(screen.getByText(/demo/)).toBeInTheDocument();
    expect(screen.getByLabelText(/permission mode/i)).toBeInTheDocument();
  });

  it("offers an attach affordance when workspace control is present but nothing is attached", () => {
    const onAttach = vi.fn();
    const workspace: WorkspaceControlInfo = {
      current: null,
      onAttach,
      onModeChange: vi.fn(),
      onDetach: vi.fn(),
    };
    render(<Composer {...baseProps()} workspace={workspace} />);
    fireEvent.click(screen.getByText(/attach folder/i));
    expect(onAttach).toHaveBeenCalledTimes(1);
  });

  it("shows a dismissible workspace_detached notice and hides it once dismissed", () => {
    render(
      <Composer
        {...baseProps()}
        workspaceDetached={{ workspaceId: "w1", text: "Workspace not found — continuing without folder access." }}
      />,
    );
    expect(screen.getByText(/continuing without folder access/i)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/dismiss/i));
    expect(screen.queryByText(/continuing without folder access/i)).not.toBeInTheDocument();
  });
});
