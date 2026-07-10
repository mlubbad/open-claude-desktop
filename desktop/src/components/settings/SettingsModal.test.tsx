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
    />,
  );
  return { onPage };
}

describe("SettingsModal shell", () => {
  it("renders the grouped nav and routes clicks through onPage", () => {
    const { onPage } = renderShell("skills");
    expect(screen.getByText("General")).toBeInTheDocument();
    expect(screen.getByText("Connectors")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Connectors"));
    expect(onPage).toHaveBeenCalledWith("connectors");
  });

  it("dispatches the active page into the body (skills -> SkillsPage)", () => {
    renderShell("skills");
    // SkillsPage renders the skill as a /name card — proof the split page mounted.
    expect(screen.getByText("/x")).toBeInTheDocument();
  });
});
