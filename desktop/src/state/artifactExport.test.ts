import { describe, expect, it } from "vitest";

import { ext, filename, mime, printableHtml, slug, typeTag } from "./artifactExport";

describe("artifact export helpers", () => {
  it("slugs titles safely", () => {
    expect(slug("Claude desktop chat UI contract!")).toBe("claude-desktop-chat-ui-contract");
    expect(slug("***")).toBe("artifact");
  });

  it("maps kinds to extensions and MIME types", () => {
    expect(ext("markdown")).toBe("md");
    expect(ext("html")).toBe("html");
    expect(ext("code", "py")).toBe("py");
    expect(ext("code")).toBe("txt");
    expect(mime("html")).toBe("text/html");
    expect(mime("svg")).toBe("image/svg+xml");
    expect(mime("unknown")).toBe("text/plain");
  });

  it("builds filenames and type tags", () => {
    expect(filename({ title: "Expiry Notifier", kind: "html", language: "" })).toBe("expiry-notifier.html");
    expect(typeTag("markdown")).toBe("MD");
    expect(typeTag("code", "py")).toBe("PY");
  });

  it("printableHtml passes rendered previews through and escapes text sheets", () => {
    expect(printableHtml("t", "x", "<!doctype html><p>hi</p>")).toBe("<!doctype html><p>hi</p>");
    const sheet = printableHtml("A <title>", "body & <code>");
    expect(sheet).toContain("A &lt;title&gt;");
    expect(sheet).toContain("body &amp; &lt;code&gt;");
    expect(sheet).toContain("<pre>");
  });
});
