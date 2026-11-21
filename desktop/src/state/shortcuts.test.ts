import { describe, expect, it } from "vitest";

import { isEditableTarget, SHORTCUTS, shortcutsFor } from "./shortcuts";

describe("SHORTCUTS", () => {
  it("lists well-formed shortcuts with unique keys", () => {
    expect(SHORTCUTS.length).toBeGreaterThanOrEqual(5);
    for (const s of SHORTCUTS) {
      expect(s.keys.trim()).not.toBe("");
      expect(s.action.trim()).not.toBe("");
    }
    const keys = SHORTCUTS.map((s) => s.keys);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("documents the palette and new-chat shortcuts, platform-aware", () => {
    const mac = shortcutsFor(true).map((s) => s.keys);
    expect(mac).toContain("⌘K");
    expect(mac).toContain("⌘⇧O");
    const win = shortcutsFor(false).map((s) => s.keys);
    expect(win).toContain("Ctrl+K");
    expect(win).toContain("Ctrl+Shift+O");
  });
});

describe("isEditableTarget", () => {
  it("is true for input/textarea/contenteditable", () => {
    expect(isEditableTarget({ tagName: "INPUT" } as unknown as EventTarget)).toBe(true);
    expect(isEditableTarget({ tagName: "TEXTAREA" } as unknown as EventTarget)).toBe(true);
    expect(isEditableTarget({ tagName: "DIV", isContentEditable: true } as unknown as EventTarget)).toBe(true);
  });

  it("is false for non-editable elements and null", () => {
    expect(isEditableTarget({ tagName: "DIV" } as unknown as EventTarget)).toBe(false);
    expect(isEditableTarget({ tagName: "BUTTON" } as unknown as EventTarget)).toBe(false);
    expect(isEditableTarget(null)).toBe(false);
  });
});
