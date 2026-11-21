import { describe, expect, it } from "vitest";

import { getDraft, setDraft } from "./drafts";

describe("drafts", () => {
  it("getDraft returns the stored text or empty", () => {
    expect(getDraft({ a: "hi" }, "a")).toBe("hi");
    expect(getDraft({}, "a")).toBe("");
  });

  it("setDraft stores non-empty text immutably", () => {
    const d0 = {};
    const d1 = setDraft(d0, "a", "hello");
    expect(d1).toEqual({ a: "hello" });
    expect(d0).toEqual({}); // original untouched
  });

  it("setDraft prunes blank entries", () => {
    expect(setDraft({ a: "x" }, "a", "")).toEqual({});
    expect(setDraft({ a: "x" }, "a", "   ")).toEqual({});
  });

  it("setDraft leaves other keys intact", () => {
    expect(setDraft({ a: "x", b: "y" }, "b", "z")).toEqual({ a: "x", b: "z" });
  });
});
