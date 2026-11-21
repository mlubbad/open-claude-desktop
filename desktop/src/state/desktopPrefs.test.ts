// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  DEFAULT_DESKTOP_PREFS,
  loadDesktopPrefs,
  onDesktopPrefsChange,
  parseDesktopPrefs,
  saveDesktopPrefs,
} from "./desktopPrefs";

describe("parseDesktopPrefs", () => {
  it("defaults both switches ON for missing/corrupt storage", () => {
    expect(parseDesktopPrefs(null)).toEqual(DEFAULT_DESKTOP_PREFS);
    expect(parseDesktopPrefs("not json {{{")).toEqual(DEFAULT_DESKTOP_PREFS);
    expect(parseDesktopPrefs("42")).toEqual(DEFAULT_DESKTOP_PREFS);
  });

  it("keeps stored booleans and fills missing fields with defaults", () => {
    expect(parseDesktopPrefs('{"summonHotkey":false}')).toEqual({ summonHotkey: false, closeToTray: true });
    expect(parseDesktopPrefs('{"closeToTray":false,"junk":1}')).toEqual({ summonHotkey: true, closeToTray: false });
    // Non-boolean values are ignored, not coerced.
    expect(parseDesktopPrefs('{"summonHotkey":"nope"}')).toEqual(DEFAULT_DESKTOP_PREFS);
  });
});

describe("save/load + change event", () => {
  beforeEach(() => localStorage.clear());

  it("round-trips through localStorage", () => {
    saveDesktopPrefs({ summonHotkey: false, closeToTray: false });
    expect(loadDesktopPrefs()).toEqual({ summonHotkey: false, closeToTray: false });
  });

  it("notifies same-window subscribers on save; unlisten stops it", () => {
    const seen = vi.fn();
    const unlisten = onDesktopPrefsChange(seen);
    saveDesktopPrefs({ summonHotkey: true, closeToTray: false });
    expect(seen).toHaveBeenCalledWith({ summonHotkey: true, closeToTray: false });
    unlisten();
    saveDesktopPrefs({ summonHotkey: false, closeToTray: true });
    expect(seen).toHaveBeenCalledTimes(1);
  });
});
