// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  checkForUpdate,
  getAppVersion,
  installUpdate,
  isLaunchAtLogin,
  isTauri,
  notify,
  registerSummonHotkey,
  setCloseToTray,
  setLaunchAtLogin,
  unregisterSummonHotkey,
} from "./platform";

// Install/remove a fake `window.__TAURI__` (what withGlobalTauri exposes).
function withTauri(global: object) {
  (window as unknown as { __TAURI__?: object }).__TAURI__ = global;
}

afterEach(() => {
  delete (window as unknown as { __TAURI__?: object }).__TAURI__;
});

// Without the Tauri global the platform layer must report "not Tauri" and degrade
// to safe no-ops / null results without throwing — this is the web build's path.
describe("platform integration (web fallback)", () => {
  it("isTauri is false without the Tauri global", () => {
    expect(isTauri()).toBe(false);
  });

  it("registerSummonHotkey returns false in a browser/no-op env", async () => {
    let fired = false;
    const ok = await registerSummonHotkey("CmdOrControl+Shift+Space", () => {
      fired = true;
    });
    expect(ok).toBe(false);
    expect(fired).toBe(false);
  });

  it("unregister + notify never throw when unavailable", async () => {
    await expect(unregisterSummonHotkey("CmdOrControl+Shift+Space")).resolves.toBeUndefined();
    await expect(notify("title", "body")).resolves.toBeUndefined();
  });

  it("shell controls degrade: version/login null-ish, update unavailable", async () => {
    expect(await getAppVersion()).toBeNull();
    expect(await isLaunchAtLogin()).toBeNull();
    expect(await setLaunchAtLogin(true)).toBe(false);
    await expect(setCloseToTray(true)).resolves.toBeUndefined();
    expect(await checkForUpdate()).toEqual({ status: "unavailable" });
    expect(await installUpdate()).toBe(false);
  });
});

describe("platform integration (fake Tauri global)", () => {
  it("launch-at-login drives the autostart plugin", async () => {
    const enable = vi.fn(async () => {});
    const disable = vi.fn(async () => {});
    withTauri({ autostart: { enable, disable, isEnabled: async () => true } });
    expect(await isLaunchAtLogin()).toBe(true);
    expect(await setLaunchAtLogin(true)).toBe(true);
    expect(enable).toHaveBeenCalled();
    expect(await setLaunchAtLogin(false)).toBe(true);
    expect(disable).toHaveBeenCalled();
  });

  it("setCloseToTray invokes the shell command with the flag", async () => {
    const invoke = vi.fn(async () => undefined);
    withTauri({ core: { invoke } });
    await setCloseToTray(false);
    expect(invoke).toHaveBeenCalledWith("set_close_to_tray", { enabled: false });
  });

  it("checkForUpdate → available keeps the handle; installUpdate installs + relaunches", async () => {
    const downloadAndInstall = vi.fn(async () => {});
    const relaunch = vi.fn(async () => {});
    withTauri({
      updater: { check: async () => ({ version: "9.9.9", body: "notes", downloadAndInstall }) },
      process: { relaunch },
    });
    expect(await checkForUpdate()).toEqual({ status: "available", version: "9.9.9", notes: "notes" });
    expect(await installUpdate()).toBe(true);
    expect(downloadAndInstall).toHaveBeenCalled();
    expect(relaunch).toHaveBeenCalled();
  });

  it("checkForUpdate → current when the feed has nothing newer", async () => {
    withTauri({ updater: { check: async () => null } });
    expect(await checkForUpdate()).toEqual({ status: "current" });
  });

  it("checkForUpdate → error when the feed is unreachable", async () => {
    withTauri({ updater: { check: async () => { throw new Error("offline"); } } });
    expect(await checkForUpdate()).toMatchObject({ status: "error" });
  });
});
