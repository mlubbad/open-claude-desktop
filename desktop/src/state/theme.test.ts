import { describe, expect, it } from "vitest";

import { isThemePref, nextTheme, resolveTheme, themeGlyph } from "./theme";

describe("resolveTheme", () => {
  it("honors explicit light/dark/glass themes regardless of system", () => {
    expect(resolveTheme("light", true)).toBe("light");
    expect(resolveTheme("light", false)).toBe("light");
    expect(resolveTheme("dark", false)).toBe("dark");
    expect(resolveTheme("glass", true)).toBe("glass");
    expect(resolveTheme("glass", false)).toBe("glass");
    expect(resolveTheme("glass-dark", false)).toBe("glass-dark");
    expect(resolveTheme("glass-dark", true)).toBe("glass-dark");
  });

  it("follows the OS when set to system", () => {
    expect(resolveTheme("system", true)).toBe("dark");
    expect(resolveTheme("system", false)).toBe("light");
  });
});

describe("nextTheme", () => {
  it("cycles system -> light -> dark -> glass -> glass-dark -> system", () => {
    expect(nextTheme("system")).toBe("light");
    expect(nextTheme("light")).toBe("dark");
    expect(nextTheme("dark")).toBe("glass");
    expect(nextTheme("glass")).toBe("glass-dark");
    expect(nextTheme("glass-dark")).toBe("system");
  });
});

describe("themeGlyph", () => {
  it("reflects the preference, not the resolved value", () => {
    expect(themeGlyph("system").label).toBe("System");
    expect(themeGlyph("light").label).toBe("Light");
    expect(themeGlyph("dark").label).toBe("Dark");
    expect(themeGlyph("glass")).toEqual({ icon: "glass", label: "Liquid Glass" });
    expect(themeGlyph("glass-dark")).toEqual({ icon: "glass-dark", label: "Liquid Glass Dark" });
  });
});

describe("isThemePref", () => {
  it("guards valid values", () => {
    expect(isThemePref("system")).toBe(true);
    expect(isThemePref("dark")).toBe(true);
    expect(isThemePref("glass")).toBe(true);
    expect(isThemePref("glass-dark")).toBe(true);
    expect(isThemePref("sepia")).toBe(false);
    expect(isThemePref(undefined)).toBe(false);
  });
});
