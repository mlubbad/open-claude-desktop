// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { RepoSyncModal } from "./RepoSyncModal";

describe("RepoSyncModal (shared useRepoSync)", () => {
  it("submits the trimmed url + ref and closes on success", async () => {
    const onSync = vi.fn(async () => null);
    const onClose = vi.fn();
    render(<RepoSyncModal title="Add skills" blurb="B" allowRemote onSync={onSync} onClose={onClose} />);
    fireEvent.change(screen.getByLabelText("Repository URL"), { target: { value: "  https://x/y.git  " } });
    fireEvent.change(screen.getByLabelText("Branch or tag (optional)"), { target: { value: " main " } });
    fireEvent.click(screen.getByRole("button", { name: "Sync" }));
    await waitFor(() => expect(onSync).toHaveBeenCalledWith("https://x/y.git", "main"));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it("shows the error and stays open when the sync fails", async () => {
    const onSync = vi.fn(async () => "boom");
    const onClose = vi.fn();
    render(<RepoSyncModal title="t" blurb="B" allowRemote onSync={onSync} onClose={onClose} />);
    fireEvent.change(screen.getByLabelText("Repository URL"), { target: { value: "https://x/y.git" } });
    fireEvent.click(screen.getByRole("button", { name: "Sync" }));
    expect(await screen.findByText("boom")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("disables Sync and warns when remote syncing is off", () => {
    render(<RepoSyncModal title="t" blurb="B" allowRemote={false} onSync={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Sync" })).toBeDisabled();
    expect(screen.getByText(/Remote syncing is disabled/)).toBeInTheDocument();
  });
});
