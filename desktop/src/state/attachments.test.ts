import { describe, expect, it } from "vitest";

import { clampContent, fenceLang, formatAttachments, MAX_ATTACH_CHARS, withAttachments } from "./attachments";

describe("clampContent", () => {
  it("passes through short content", () => {
    expect(clampContent("hello")).toBe("hello");
  });
  it("truncates content over the cap", () => {
    const big = "x".repeat(MAX_ATTACH_CHARS + 500);
    const out = clampContent(big);
    expect(out.length).toBeLessThan(big.length);
    expect(out.endsWith("[truncated]")).toBe(true);
  });
});

describe("fenceLang", () => {
  it("maps known extensions", () => {
    expect(fenceLang("main.py")).toBe("python");
    expect(fenceLang("data.json")).toBe("json");
    expect(fenceLang("notes.md")).toBe("markdown");
  });
  it("returns empty for unknown", () => {
    expect(fenceLang("file.xyz")).toBe("");
    expect(fenceLang("noext")).toBe("");
  });
});

describe("formatAttachments", () => {
  it("renders each file as a named fenced block", () => {
    const out = formatAttachments([{ name: "a.py", content: "print(1)" }]);
    expect(out).toContain("Attached file: a.py");
    expect(out).toContain("```python");
    expect(out).toContain("print(1)");
  });
});

describe("withAttachments", () => {
  it("returns the text unchanged when there are no attachments", () => {
    expect(withAttachments("hi", [])).toBe("hi");
  });
  it("appends attachments after the message", () => {
    const out = withAttachments("Review this", [{ name: "a.txt", content: "body" }]);
    expect(out.startsWith("Review this")).toBe(true);
    expect(out).toContain("Attached file: a.txt");
  });
  it("uses only the attachment block when there is no message text", () => {
    const out = withAttachments("   ", [{ name: "a.txt", content: "body" }]);
    expect(out.startsWith("Attached file: a.txt")).toBe(true);
  });
});
