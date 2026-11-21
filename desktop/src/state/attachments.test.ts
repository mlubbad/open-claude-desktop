import { describe, expect, it } from "vitest";

import {
  admitImages,
  clampContent,
  fenceLang,
  formatAttachments,
  isImageFile,
  MAX_ATTACH_CHARS,
  MAX_IMAGE_BYTES,
  MAX_IMAGES,
  parseAttachments,
  withAttachments,
} from "./attachments";

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

describe("parseAttachments", () => {
  it("round-trips withAttachments back into body + files", () => {
    const files = [
      { name: "a.py", content: "print(1)" },
      { name: "notes.md", content: "# hi\n\nmore text" },
    ];
    const wire = withAttachments("Review these", files);
    const parsed = parseAttachments(wire);
    expect(parsed.body).toBe("Review these");
    expect(parsed.files).toEqual(files);
  });
  it("round-trips an attachment-only message (empty body)", () => {
    const wire = withAttachments("", [{ name: "a.txt", content: "body" }]);
    const parsed = parseAttachments(wire);
    expect(parsed.body).toBe("");
    expect(parsed.files).toEqual([{ name: "a.txt", content: "body" }]);
  });
  it("leaves plain messages untouched", () => {
    const parsed = parseAttachments("Just a normal message\n\nwith paragraphs");
    expect(parsed.body).toBe("Just a normal message\n\nwith paragraphs");
    expect(parsed.files).toEqual([]);
  });
  it("does not treat a mid-message fenced block as an attachment", () => {
    const text = "Attached file: fake.txt\n\n```\nnot at end\n```\n\ntrailing prose";
    const parsed = parseAttachments(text);
    expect(parsed.body).toBe(text);
    expect(parsed.files).toEqual([]);
  });
});

describe("image attachments", () => {
  it("isImageFile keys off the MIME type", () => {
    expect(isImageFile({ type: "image/png" })).toBe(true);
    expect(isImageFile({ type: "image/webp" })).toBe(true);
    expect(isImageFile({ type: "text/plain" })).toBe(false);
    expect(isImageFile({ type: "" })).toBe(false);
  });

  it("admitImages enforces the size cap and the total count", () => {
    const small = { size: 1000 };
    const huge = { size: MAX_IMAGE_BYTES + 1 };
    expect(admitImages(0, [small, huge, small])).toEqual([small, small]);
    // Already 5 attached -> only 1 slot left of MAX_IMAGES (6).
    expect(admitImages(5, [small, small, small])).toEqual([small]);
    // Full -> nothing admitted.
    expect(admitImages(MAX_IMAGES, [small])).toEqual([]);
  });
});
