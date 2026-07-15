// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";

import { applyUiPrefs, FONT_OPTIONS, getChatFont, getMotion, setChatFont, setMotion } from "./uiPrefs";

describe("uiPrefs", () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.chatFont;
    delete document.documentElement.dataset.motion;
    document.documentElement.style.removeProperty("--font-serif");
  });

  it("defaults to serif + system motion and no --font-serif override", () => {
    expect(getChatFont()).toBe("serif");
    expect(getMotion()).toBe("system");
    applyUiPrefs();
    expect(document.documentElement.dataset.chatFont).toBe("serif");
    expect(document.documentElement.dataset.motion).toBe("system");
    // The default clears the inline var so the editorial :root stack applies.
    expect(document.documentElement.style.getPropertyValue("--font-serif")).toBe("");
  });

  it("persists and applies a concrete font by setting --font-serif inline", () => {
    setChatFont("noto");
    setMotion("reduced");
    expect(document.documentElement.dataset.chatFont).toBe("noto");
    expect(document.documentElement.dataset.motion).toBe("reduced");
    const stack = FONT_OPTIONS.find((o) => o.value === "noto")!.stack!;
    expect(document.documentElement.style.getPropertyValue("--font-serif")).toBe(stack);
    // A fresh read (new session) sees the persisted values.
    expect(getChatFont()).toBe("noto");
    expect(getMotion()).toBe("reduced");
  });

  it("switching back to the default serif removes the inline override", () => {
    setChatFont("georgia");
    expect(document.documentElement.style.getPropertyValue("--font-serif")).not.toBe("");
    setChatFont("serif");
    expect(document.documentElement.style.getPropertyValue("--font-serif")).toBe("");
  });

  it("maps the legacy \"sans\" value onto the system-sans option", () => {
    localStorage.setItem("ocd.chatFont", "sans");
    expect(getChatFont()).toBe("system");
    applyUiPrefs();
    expect(document.documentElement.dataset.chatFont).toBe("system");
  });

  it("treats unknown stored values as the defaults", () => {
    localStorage.setItem("ocd.chatFont", "wingdings");
    localStorage.setItem("ocd.motion", "chaotic");
    expect(getChatFont()).toBe("serif");
    expect(getMotion()).toBe("system");
  });
});
