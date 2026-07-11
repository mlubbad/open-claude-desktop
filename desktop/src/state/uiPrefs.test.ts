// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";

import { applyUiPrefs, getChatFont, getMotion, setChatFont, setMotion } from "./uiPrefs";

describe("uiPrefs", () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.chatFont;
    delete document.documentElement.dataset.motion;
  });

  it("defaults to serif + system motion", () => {
    expect(getChatFont()).toBe("serif");
    expect(getMotion()).toBe("system");
    applyUiPrefs();
    expect(document.documentElement.dataset.chatFont).toBe("serif");
    expect(document.documentElement.dataset.motion).toBe("system");
  });

  it("persists and applies changes to <html> immediately", () => {
    setChatFont("sans");
    setMotion("reduced");
    expect(document.documentElement.dataset.chatFont).toBe("sans");
    expect(document.documentElement.dataset.motion).toBe("reduced");
    // A fresh read (new session) sees the persisted values.
    expect(getChatFont()).toBe("sans");
    expect(getMotion()).toBe("reduced");
  });

  it("treats unknown stored values as the defaults", () => {
    localStorage.setItem("ocd.chatFont", "wingdings");
    localStorage.setItem("ocd.motion", "chaotic");
    expect(getChatFont()).toBe("serif");
    expect(getMotion()).toBe("system");
  });
});
