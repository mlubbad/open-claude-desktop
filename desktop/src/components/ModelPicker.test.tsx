// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DEFAULT_PICKER_COUNT } from "../state/modelMeta";
import { ModelPicker } from "./ModelPicker";

const MODELS = [
  "nova-70b",
  "nova-12b",
  "nova-8b",
  "zephyr-max",
  "zephyr-mini",
  "orion-2",
  "orion-1",
  "legacy-x",
];

vi.mock("../api/client", () => ({
  providers: {
    list: vi.fn(async () => [
      {
        id: "nim", label: "NVIDIA NIM", is_local: false, requires_key: true, has_key: true,
        default_model: "nova-70b", models: [...MODELS], docs: "", is_default: true,
      },
    ]),
  },
  settings: { get: vi.fn(async () => ({})) },
}));

function renderPicker(over: Partial<Parameters<typeof ModelPicker>[0]> = {}) {
  const props = {
    provider: "nim",
    model: "orion-1",
    effort: "High",
    thinking: false,
    onSelectModel: vi.fn(),
    onSelectEffort: vi.fn(),
    onToggleThinking: vi.fn(),
    onMoreModels: vi.fn(),
    onClose: vi.fn(),
    ...over,
  };
  const utils = render(<ModelPicker {...props} />);
  return { ...utils, props };
}

describe("ModelPicker", () => {
  it("shows the newest few models plus the current one after the async load", async () => {
    const { container } = renderPicker();
    await screen.findByText("nova-70b");
    // First DEFAULT_PICKER_COUNT of the catalog + the out-of-range current model.
    expect(container.querySelectorAll(".mp-model").length).toBe(DEFAULT_PICKER_COUNT + 1);
    expect(screen.getByText("orion-1")).toBeInTheDocument();
    expect(screen.queryByText("legacy-x")).not.toBeInTheDocument();
  });

  it("selecting a model reports provider + model", async () => {
    const { props } = renderPicker();
    fireEvent.click(await screen.findByText("nova-12b"));
    expect(props.onSelectModel).toHaveBeenCalledWith("nim", "nova-12b");
  });

  it("selecting an effort level reports it", async () => {
    const { props } = renderPicker();
    fireEvent.click(screen.getByRole("button", { name: /Max/ }));
    expect(props.onSelectEffort).toHaveBeenCalledWith("Max");
    await waitFor(() => {}); // flush the async provider load before unmount
  });

  it("the Thinking switch toggles", async () => {
    const { props } = renderPicker();
    fireEvent.click(screen.getByRole("switch", { name: "Thinking" }));
    expect(props.onToggleThinking).toHaveBeenCalledWith(true);
    await waitFor(() => {});
  });

  it("More models & keys jumps to Settings", async () => {
    const { props } = renderPicker();
    fireEvent.click(await screen.findByRole("button", { name: /More models & keys/ }));
    expect(props.onMoreModels).toHaveBeenCalled();
  });

  it("Escape and outside clicks close the popover", async () => {
    const { props } = renderPicker();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(props.onClose).toHaveBeenCalledTimes(1);
    fireEvent.mouseDown(document.body);
    expect(props.onClose).toHaveBeenCalledTimes(2);
    await waitFor(() => {});
  });
});
