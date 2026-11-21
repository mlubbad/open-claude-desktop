import { describe, expect, it } from "vitest";

import { STARTER_PROMPTS } from "./starters";

describe("STARTER_PROMPTS", () => {
  it("offers a few well-formed suggestions", () => {
    expect(STARTER_PROMPTS.length).toBeGreaterThanOrEqual(4);
    for (const s of STARTER_PROMPTS) {
      expect(s.label.trim()).not.toBe("");
      expect(s.prompt.trim().length).toBeGreaterThan(10);
      expect(s.icon.trim()).not.toBe("");
    }
  });

  it("has unique labels", () => {
    const labels = STARTER_PROMPTS.map((s) => s.label);
    expect(new Set(labels).size).toBe(labels.length);
  });
});
