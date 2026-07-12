// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DesktopGeneralPage } from "./DesktopGeneralPage";

function withTauri(global: object) {
  (window as unknown as { __TAURI__?: object }).__TAURI__ = global;
}

beforeEach(() => localStorage.clear());
afterEach(() => {
  delete (window as unknown as { __TAURI__?: object }).__TAURI__;
});

describe("DesktopGeneralPage (web)", () => {
  it("renders the shell switches disabled with a pointer to the desktop app", () => {
    render(<DesktopGeneralPage />);
    expect(screen.getByText(/open the desktop app to change them/i)).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "System tray" })).toBeDisabled();
    expect(screen.getByRole("switch", { name: "Launch at login" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Check for updates" })).toBeDisabled();
  });
});

describe("DesktopGeneralPage (desktop shell)", () => {
  it("System tray toggle persists the pref and fires the change event", async () => {
    withTauri({});
    const seen = vi.fn();
    window.addEventListener("ocd:desktop-prefs", seen);
    render(<DesktopGeneralPage />);
    const tray = screen.getByRole("switch", { name: "System tray" });
    expect(tray).toBeEnabled();
    expect(tray).toHaveAttribute("aria-checked", "true"); // default ON
    fireEvent.click(tray);
    expect(tray).toHaveAttribute("aria-checked", "false");
    expect(JSON.parse(localStorage.getItem("ocd.desktopPrefs")!)).toMatchObject({ closeToTray: false });
    expect(seen).toHaveBeenCalled();
    window.removeEventListener("ocd:desktop-prefs", seen);
  });

  it("Launch at login reads the OS entry and enables it on toggle", async () => {
    const enable = vi.fn(async () => {});
    withTauri({ autostart: { enable, disable: vi.fn(), isEnabled: async () => false } });
    render(<DesktopGeneralPage />);
    const login = screen.getByRole("switch", { name: "Launch at login" });
    await waitFor(() => expect(login).toBeEnabled());
    fireEvent.click(login);
    await waitFor(() => expect(login).toHaveAttribute("aria-checked", "true"));
    expect(enable).toHaveBeenCalled();
  });

  it("Check for updates flips to an install button when one is available", async () => {
    withTauri({
      app: { getVersion: async () => "0.1.0" },
      updater: {
        check: async () => ({ version: "0.2.0", body: "bug fixes", downloadAndInstall: vi.fn() }),
      },
    });
    render(<DesktopGeneralPage />);
    fireEvent.click(screen.getByRole("button", { name: "Check for updates" }));
    expect(await screen.findByRole("button", { name: "Restart & install v0.2.0" })).toBeInTheDocument();
    expect(screen.getByText(/bug fixes/)).toBeInTheDocument();
  });

  it("Check for updates reports being current", async () => {
    withTauri({ updater: { check: async () => null } });
    render(<DesktopGeneralPage />);
    fireEvent.click(screen.getByRole("button", { name: "Check for updates" }));
    expect(await screen.findByText(/latest version/i)).toBeInTheDocument();
  });
});
