import { describe, expect, it } from "vitest";

import {
  ext,
  filename,
  isPreviewable,
  mime,
  parseCsv,
  previewMarkdown,
  printableHtml,
  slug,
  sniffDelimiter,
  typeTag,
} from "./artifactExport";

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

describe("isPreviewable", () => {
  it("previews iframe kinds", () => {
    for (const k of ["html", "svg", "mermaid", "react"]) expect(isPreviewable(k)).toBe(true);
  });
  it("previews markdown, code, and plain text (so the eye toggle always works)", () => {
    expect(isPreviewable("markdown")).toBe(true);
    expect(isPreviewable("code")).toBe(true);
    expect(isPreviewable("text")).toBe(true);
    expect(isPreviewable("")).toBe(true); // untyped artifacts default to previewable
  });
  it("is not previewable for unknown kinds", () => {
    expect(isPreviewable("binary")).toBe(false);
  });
});

describe("csv artifact", () => {
  it("is previewable and maps to a .csv/text-csv download", () => {
    expect(isPreviewable("csv")).toBe(true);
    expect(ext("csv")).toBe("csv");
    expect(mime("csv")).toBe("text/csv");
    expect(typeTag("csv")).toBe("CSV");
    expect(filename({ title: "Merged Campaign Data", kind: "csv", language: "" })).toBe("merged-campaign-data.csv");
  });
});

describe("parseCsv", () => {
  it("splits a header row and body rows", () => {
    const { columns, rows } = parseCsv("Country,Clicks\nUS,134\nEgypt,111");
    expect(columns).toEqual(["Country", "Clicks"]);
    expect(rows).toEqual([
      ["US", "134"],
      ["Egypt", "111"],
    ]);
  });

  it("honours quoted fields with commas, escaped quotes, and newlines", () => {
    const { columns, rows } = parseCsv('a,b\n"x, y","she said ""hi"""\n"multi\nline",z');
    expect(columns).toEqual(["a", "b"]);
    expect(rows[0]).toEqual(["x, y", 'she said "hi"']);
    expect(rows[1]).toEqual(["multi\nline", "z"]);
  });

  it("ignores a trailing newline and handles CRLF", () => {
    expect(parseCsv("a,b\r\n1,2\r\n").rows).toEqual([["1", "2"]]);
    expect(parseCsv("").columns).toEqual([]);
  });

  it("auto-detects a semicolon delimiter (European CSV) and tabs", () => {
    expect(sniffDelimiter("Campaign ID;Date;Country;Clicks")).toBe(";");
    expect(sniffDelimiter("a,b,c")).toBe(",");
    expect(sniffDelimiter("a\tb\tc")).toBe("\t");
    const { columns, rows } = parseCsv("Campaign ID;Date;Country;Clicks\n412;02-07-2026;Saudi Arabia;14");
    expect(columns).toEqual(["Campaign ID", "Date", "Country", "Clicks"]);
    expect(rows).toEqual([["412", "02-07-2026", "Saudi Arabia", "14"]]);
  });
});

describe("previewMarkdown", () => {
  it("returns nothing for iframe kinds (they render in the sandbox)", () => {
    expect(previewMarkdown("html", "<p>hi</p>")).toBe("");
    expect(previewMarkdown("svg", "<svg/>")).toBe("");
  });
  it("passes a markdown artifact through unchanged", () => {
    expect(previewMarkdown("markdown", "# Heading\n\ntext")).toBe("# Heading\n\ntext");
  });
  it("wraps code in a language-tagged fence for syntax highlighting", () => {
    expect(previewMarkdown("code", "print('hi')", "python")).toBe("```python\nprint('hi')\n```");
    // No language → an untagged fence.
    expect(previewMarkdown("text", "plain")).toBe("```\nplain\n```");
  });
  it("uses a ~~~ fence when the source itself contains ```", () => {
    const md = previewMarkdown("code", "a\n```\nb", "md");
    expect(md.startsWith("~~~md\n")).toBe(true);
    expect(md.endsWith("\n~~~")).toBe(true);
    expect(md).toContain("```"); // the inner backticks survive intact
  });
});
