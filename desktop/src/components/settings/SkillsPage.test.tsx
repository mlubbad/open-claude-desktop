// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SkillsPage } from "./SkillsPage";
import type { SkillControls } from "./types";

function makeControls(over: Partial<SkillControls> = {}): SkillControls {
  return {
    list: [
      { name: "hero", description: "Hero help", auto: true, triggers: ["hero"], imported: true },
      { name: "bundled", description: "Bundled", imported: false },
    ],
    busy: false,
    allowRemote: true,
    importFile: vi.fn(async () => null),
    importZip: vi.fn(async () => null),
    importFromRepo: vi.fn(async () => null),
    onRemove: vi.fn(),
    ...over,
  };
}

describe("SkillsPage", () => {
  it("renders a card per skill with its /name title", () => {
    render(<SkillsPage c={makeControls()} />);
    expect(screen.getByText("/hero")).toBeInTheDocument();
    expect(screen.getByText("/bundled")).toBeInTheDocument();
  });

  it("offers Remove only for imported skills and calls onRemove", () => {
    const c = makeControls();
    render(<SkillsPage c={c} />);
    expect(screen.queryByLabelText("Remove bundled")).toBeNull(); // bundled is not removable
    fireEvent.click(screen.getByLabelText("Remove hero"));
    expect(c.onRemove).toHaveBeenCalledWith("hero");
  });

  it("filters the grid by the search box", () => {
    render(<SkillsPage c={makeControls()} />);
    fireEvent.change(screen.getByPlaceholderText("Search skills…"), { target: { value: "hero" } });
    expect(screen.getByText("/hero")).toBeInTheDocument();
    expect(screen.queryByText("/bundled")).toBeNull();
  });

  it("shows the empty state when there are no skills", () => {
    render(<SkillsPage c={makeControls({ list: [] })} />);
    expect(screen.getByText(/No skills yet/)).toBeInTheDocument();
  });
});

// Import routing: claude.ai distributes skills as `.skill` bundles (zip under another
// extension). The picker must offer them and they must take the archive path — before
// this, the file dialog's filter simply hid every .skill file from the user.
describe("SkillsPage import routing", () => {
  function pickFile(container: HTMLElement, file: File) {
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file] } });
  }

  it("accepts .skill in the file picker (claude.ai skill bundles)", () => {
    const { container } = render(<SkillsPage c={makeControls()} />);
    const input = container.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input.accept).toContain(".skill");
    expect(input.accept).toContain(".zip");
    expect(input.accept).toContain(".md");
  });

  it("routes a .skill bundle through the archive importer, not the text one", async () => {
    const c = makeControls();
    const { container } = render(<SkillsPage c={c} />);
    pickFile(container, new File(["PK\x03\x04zipbytes"], "watch.skill"));
    await waitFor(() => expect(c.importZip).toHaveBeenCalledTimes(1));
    expect(c.importFile).not.toHaveBeenCalled();
  });

  it("still routes .zip to the archive importer and .md to the text importer", async () => {
    const c = makeControls();
    const { container } = render(<SkillsPage c={c} />);
    pickFile(container, new File(["PK\x03\x04zipbytes"], "bundle.zip"));
    await waitFor(() => expect(c.importZip).toHaveBeenCalledTimes(1));
    const md = new File([""], "x.md");
    // jsdom's File has no Blob.text(); the component reads it, so provide one.
    Object.defineProperty(md, "text", { value: async () => "---\nname: x\n---\nhello" });
    pickFile(container, md);
    await waitFor(() => expect(c.importFile).toHaveBeenCalledTimes(1));
    expect(c.importFile).toHaveBeenCalledWith("x.md", "---\nname: x\n---\nhello");
  });
});
