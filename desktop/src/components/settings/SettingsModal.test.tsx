// @vitest-environment jsdom
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SettingsModal } from "../SettingsModal";
import type { ConnectorControls, PluginControls, SkillControls } from "./types";

const skills: SkillControls = {
  list: [{ name: "x", imported: true }],
  busy: false,
  allowRemote: true,
  importFile: vi.fn(async () => null),
  importZip: vi.fn(async () => null),
  importFromRepo: vi.fn(async () => null),
  onRemove: vi.fn(),
};
const conn: ConnectorControls = {
  servers: [],
  enabled: [],
  err: null,
  onAdd: vi.fn(),
  onInstall: vi.fn(),
  onAddOAuth: vi.fn(),
  onAuthorize: vi.fn(),
  onRemove: vi.fn(),
  onToggle: vi.fn(),
  onRetry: vi.fn(),
  retrying: null,
};
const plug: PluginControls = {
  installed: [],
  market: [],
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
};

function renderShell(page: React.ComponentProps<typeof SettingsModal>["page"], onPage = vi.fn()) {
  render(
    <SettingsModal
      page={page}
      onPage={onPage}
      onClose={vi.fn()}
      active={{ provider: "p", model: "m" }}
      onPick={vi.fn()}
      skills={skills}
      conn={conn}
      plug={plug}
      theme={{ pref: "system", set: vi.fn() }}
    />,
  );
  return { onPage };
}

describe("SettingsModal shell", () => {
  it("renders the three nav groups and routes clicks through onPage", () => {
    const { onPage } = renderShell("skills");
    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(screen.getByText("Desktop app")).toBeInTheDocument();
    expect(screen.getByText("Customize")).toBeInTheDocument();
    // Two "General" entries: Settings + Desktop app — both present.
    expect(screen.getAllByText("General")).toHaveLength(2);
    fireEvent.click(screen.getByText("Connectors"));
    expect(onPage).toHaveBeenCalledWith("connectors");
  });

  it("dispatches the active page into the body (skills -> SkillsPage)", () => {
    renderShell("skills");
    // SkillsPage renders the skill as a /name card — proof the split page mounted.
    expect(screen.getByText("/x")).toBeInTheDocument();
  });

  it("nav search filters items by label and keywords", () => {
    renderShell("general");
    fireEvent.change(screen.getByLabelText("Search settings"), { target: { value: "mcpb" } });
    // "mcpb" is an Extensions keyword — only that item survives.
    expect(screen.getByText("Extensions")).toBeInTheDocument();
    expect(screen.queryByText("Privacy")).toBeNull();
    expect(screen.queryByText("Billing")).toBeNull();
  });

  it("unimplemented pages render faithfully but disabled (Account)", () => {
    renderShell("account");
    const logout = screen.getByRole("button", { name: "Log out" });
    expect(logout).toBeDisabled();
    expect(logout).toHaveAttribute("title", expect.stringContaining("Not available"));
  });

  it("Claude in Chrome page renders its disabled site-permission controls", () => {
    renderShell("chrome");
    expect(screen.getByLabelText("Site permissions")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add website" })).toBeDisabled();
  });
});
