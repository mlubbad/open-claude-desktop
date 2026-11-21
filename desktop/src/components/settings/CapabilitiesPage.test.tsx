// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CapabilitiesPage } from "./CapabilitiesPage";

const saveSpy = vi.fn(async (patch: object) => ({ ...patch }));
vi.mock("../../api/client", () => ({
  settings: {
    get: vi.fn(async () => ({
      search_provider: "ddg", searxng_url: "", code_execution: "auto",
      permission_mode: "ask",
    })),
    save: (patch: object) => saveSpy(patch),
  },
  observability: {
    get: vi.fn(async () => ({
      enabled: false, mode: "local", url: "", project: "p", workspace: "",
      has_key: false, sdk_installed: true,
    })),
  },
}));

describe("CapabilitiesPage", () => {
  beforeEach(() => saveSpy.mockClear());

  it("saves ONLY the changed field — the stale-closure resubmit is gone", async () => {
    render(<CapabilitiesPage />);
    await waitFor(() =>
      expect(screen.getByLabelText("Permission mode")).toHaveValue("ask"));
    fireEvent.change(screen.getByLabelText("Permission mode"), { target: { value: "auto" } });
    await waitFor(() => expect(saveSpy).toHaveBeenCalled());
    expect(saveSpy.mock.calls.at(-1)![0]).toEqual({ permission_mode: "auto" });
  });

  it("search backend select saves its own patch and reveals the SearXNG URL field", async () => {
    render(<CapabilitiesPage />);
    await waitFor(() => expect(screen.getByLabelText("Search backend")).toHaveValue("ddg"));
    fireEvent.change(screen.getByLabelText("Search backend"), { target: { value: "searxng" } });
    expect(saveSpy.mock.calls.at(-1)![0]).toEqual({ search_provider: "searxng" });
    expect(screen.getByLabelText("SearXNG base URL")).toBeInTheDocument();
  });

  it("unbacked rows render disabled", async () => {
    render(<CapabilitiesPage />);
    await waitFor(() => expect(screen.getByLabelText("Search backend")).toBeInTheDocument());
    expect(screen.getByLabelText("Connector search")).toBeDisabled();
    expect(screen.getByLabelText("Tool access mode")).toBeDisabled();
    expect(screen.getByLabelText("Allow network egress")).toBeDisabled();
  });

  it("memory: 'Search and reference chats' is a real toggle saving memory_search", async () => {
    render(<CapabilitiesPage />);
    await waitFor(() =>
      expect(screen.getByLabelText("Search and reference chats")).toBeEnabled());
    fireEvent.click(screen.getByLabelText("Search and reference chats"));
    await waitFor(() => expect(saveSpy).toHaveBeenCalled());
    expect(saveSpy.mock.calls.at(-1)![0]).toEqual({ memory_search: false });
  });

  it("'Pause all automations' is a real toggle saving the autonomy_paused kill-switch", async () => {
    render(<CapabilitiesPage />);
    await waitFor(() =>
      expect(screen.getByLabelText("Pause all automations")).toBeEnabled());
    fireEvent.click(screen.getByLabelText("Pause all automations"));
    await waitFor(() => expect(saveSpy).toHaveBeenCalled());
    expect(saveSpy.mock.calls.at(-1)![0]).toEqual({ autonomy_paused: true });
  });
});
