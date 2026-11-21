// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ObservabilitySection } from "./ObservabilitySection";

const state = {
  status: {
    enabled: true, mode: "cloud", url: "", project: "open-claude-desktop",
    workspace: "", has_key: false, sdk_installed: true,
  },
};
const saveSpy = vi.fn(async (patch: object) => ({ ...patch }));
const setKeySpy = vi.fn(async (_key: string) => ({ has_key: true }));
const clearKeySpy = vi.fn(async () => ({ has_key: false }));

vi.mock("../../api/client", () => ({
  settings: { get: vi.fn(async () => ({})), save: (p: object) => saveSpy(p) },
  observability: {
    get: vi.fn(async () => ({ ...state.status })),
    setKey: (k: string) => setKeySpy(k),
    clearKey: () => clearKeySpy(),
  },
}));

describe("ObservabilitySection", () => {
  beforeEach(() => {
    saveSpy.mockClear();
    setKeySpy.mockClear();
    clearKeySpy.mockClear();
    state.status.has_key = false;
    state.status.mode = "cloud";
    state.status.sdk_installed = true;
  });

  it("shouts when tracing is on but the SDK is missing (install banner)", async () => {
    state.status.sdk_installed = false;
    render(<ObservabilitySection />);
    const banner = await screen.findByRole("alert");
    expect(banner.textContent).toContain("No traces are being sent");
    expect(banner.textContent).toContain(".venv\\Scripts\\pip install opik"); // Windows
    expect(banner.textContent).toContain(".venv/bin/pip install opik"); // macOS/Linux
    expect(banner.textContent).toContain("toggle tracing off and back on");
  });

  it("tells the user what traces contain (consent copy)", async () => {
    render(<ObservabilitySection />);
    await waitFor(() =>
      expect(screen.getByText(/Traces include your prompts, tool inputs, and answers/))
        .toBeInTheDocument());
  });

  it("saving a Cloud API key goes through the keychain endpoint, never settings", async () => {
    render(<ObservabilitySection />);
    await waitFor(() => expect(screen.getByLabelText("Opik Cloud API key")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Opik Cloud API key"), { target: { value: "sk-op-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Save key" }));
    await waitFor(() => expect(setKeySpy).toHaveBeenCalledWith("sk-op-1"));
    expect(saveSpy).not.toHaveBeenCalled(); // the key never touches /settings
    // The UI flips to the saved state with a Remove action.
    await waitFor(() => expect(screen.getByText("Key saved ✓")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(clearKeySpy).toHaveBeenCalled());
  });

  it("the deployment switch persists opik_mode as its own patch", async () => {
    render(<ObservabilitySection />);
    await waitFor(() => expect(screen.getByLabelText("Opik deployment")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("radio", { name: "Self-hosted" }));
    await waitFor(() => expect(saveSpy).toHaveBeenCalledWith({ opik_mode: "local" }));
    // Local mode shows the self-hosted URL field instead of the key row.
    expect(screen.getByLabelText("Opik URL")).toBeInTheDocument();
    expect(screen.queryByLabelText("Opik Cloud API key")).toBeNull();
  });

  it("disabling the toggle saves only opik_enabled", async () => {
    render(<ObservabilitySection />);
    await waitFor(() => expect(screen.getByLabelText("Trace agent turns")).toBeInTheDocument());
    fireEvent.click(screen.getByLabelText("Trace agent turns"));
    await waitFor(() => expect(saveSpy).toHaveBeenCalledWith({ opik_enabled: false }));
  });
});
