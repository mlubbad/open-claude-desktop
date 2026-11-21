// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { PluginsPage } from "./PluginsPage";
import type { PluginControls } from "./types";

function makeControls(over: Partial<PluginControls> = {}): PluginControls {
  return {
    installed: [{ name: "calc", description: "Calculator" }],
    market: [
      { name: "calc", description: "Calculator", category: "Math", installed: true },
      { name: "colors", description: "Color tools", category: "Design", installed: false },
    ],
    sources: [],
    allowRemote: true,
    enabled: [],
    err: null,
    busy: null,
    onToggle: vi.fn(),
    onInstall: vi.fn(),
    onUninstall: vi.fn(),
    onAddSource: vi.fn(async () => null),
    onRemoveSource: vi.fn(),
    ...over,
  };
}

describe("PluginsPage", () => {
  it("offers Uninstall only for an installed plugin that exists in the marketplace", () => {
    const c = makeControls();
    render(<PluginsPage p={c} />);
    fireEvent.click(screen.getByLabelText("Uninstall calc"));
    expect(c.onUninstall).toHaveBeenCalledWith("calc");
  });

  it("does NOT offer Uninstall for a built-in absent from the marketplace", () => {
    const c = makeControls({
      installed: [{ name: "builtin", description: "B" }],
      market: [{ name: "colors", description: "Color tools", category: "Design", installed: false }],
    });
    render(<PluginsPage p={c} />);
    expect(screen.queryByLabelText("Uninstall builtin")).toBeNull();
  });

  it("Install triggers onInstall for a not-yet-installed marketplace plugin", () => {
    const c = makeControls();
    render(<PluginsPage p={c} />);
    fireEvent.click(screen.getByRole("button", { name: "Install" }));
    expect(c.onInstall).toHaveBeenCalledWith("colors");
  });

  it("Add marketplace: choose → form → submit passes url/ref/name to onAddSource", async () => {
    const c = makeControls();
    render(<PluginsPage p={c} />);
    fireEvent.click(screen.getByRole("button", { name: /Add marketplace/ }));
    fireEvent.click(screen.getByText("Add from a repository")); // advance past the choose step
    fireEvent.change(screen.getByLabelText("Repository URL"), { target: { value: "https://x/y.git" } });
    fireEvent.change(screen.getByLabelText("Display name (optional)"), { target: { value: "My MP" } });
    fireEvent.click(screen.getByRole("button", { name: "Sync marketplace" }));
    await waitFor(() => expect(c.onAddSource).toHaveBeenCalledWith("https://x/y.git", "", "My MP"));
  });
});
