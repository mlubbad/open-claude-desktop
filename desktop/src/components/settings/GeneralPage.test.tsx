// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GeneralPage } from "./GeneralPage";

const saveSpy = vi.fn(async (patch: object) => ({ ...patch }));
vi.mock("../../api/client", () => ({
  settings: {
    get: vi.fn(async () => ({ profile: { name: "Ada Lovelace", call_me: "Ada" } })),
    save: (patch: object) => saveSpy(patch),
  },
  observability: { get: vi.fn(async () => ({})) },
}));

function renderPage(setTheme = vi.fn()) {
  render(<GeneralPage theme={{ pref: "system", set: setTheme }} />);
  return { setTheme };
}

describe("GeneralPage", () => {
  beforeEach(() => saveSpy.mockClear());

  it("loads the profile and shows avatar initials", async () => {
    renderPage();
    await waitFor(() =>
      expect(screen.getByLabelText("Full name")).toHaveValue("Ada Lovelace"));
    expect(screen.getByLabelText("Avatar initials").textContent).toBe("AL");
  });

  it("saves ONLY a profile patch on blur (no stale sibling fields)", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByLabelText("Full name")).toHaveValue("Ada Lovelace"));
    const name = screen.getByLabelText("Full name");
    fireEvent.change(name, { target: { value: "Grace Hopper" } });
    fireEvent.blur(name);
    await waitFor(() => expect(saveSpy).toHaveBeenCalled());
    const patch = saveSpy.mock.calls.at(-1)![0] as Record<string, unknown>;
    expect(Object.keys(patch)).toEqual(["profile"]);
    expect((patch.profile as Record<string, string>).name).toBe("Grace Hopper");
    expect((patch.profile as Record<string, string>).call_me).toBe("Ada"); // preserved
  });

  it("the appearance segmented drives the real theme setter", async () => {
    const { setTheme } = renderPage();
    await waitFor(() => expect(screen.getByLabelText("Full name")).toBeInTheDocument());
    fireEvent.click(screen.getByTitle("Dark"));
    expect(setTheme).toHaveBeenCalledWith("dark");
  });

  it("chat font select persists via uiPrefs onto <html> and applies the font", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByLabelText("Chat font")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Chat font"), { target: { value: "noto" } });
    expect(document.documentElement.dataset.chatFont).toBe("noto");
    // The chosen font actually drives the app-wide serif variable.
    expect(document.documentElement.style.getPropertyValue("--font-serif")).toContain("Noto Serif");
  });

  it("voice rows render faithfully but disabled (no backend)", async () => {
    renderPage();
    await waitFor(() => expect(screen.getByLabelText("Voice language")).toBeDisabled());
    expect(screen.getByLabelText("Voice style")).toBeDisabled();
  });
});
