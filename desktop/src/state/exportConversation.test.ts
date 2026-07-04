import { describe, expect, it } from "vitest";

import { exportSlug, toJSON, toMarkdown } from "./exportConversation";
import type { Message } from "./transcript";

const sample: Message[] = [
  { role: "user", text: "What is 2+2?" },
  {
    role: "assistant",
    blocks: [
      { kind: "thinking", phase: "", text: "simple arithmetic", streaming: false },
      {
        kind: "tool",
        id: "t1",
        name: "calc",
        input: "2+2",
        labelRunning: "Calculating",
        labelDone: "Calculated",
        icon: "database",
        status: "done",
        summary: "= 4",
      },
      { kind: "answer", text: "It's **4**.", streaming: false },
      {
        kind: "artifact",
        doc: {
          id: "a1", title: "Chart", kind: "html", language: "",
          content: "<h1>4</h1>", version: 2, streaming: false, versions: ["<h1>4</h1>"],
        },
      },
    ],
  },
];

describe("toMarkdown", () => {
  const md = toMarkdown(sample, "Math chat");

  it("has a title and turn headings", () => {
    expect(md).toContain("# Math chat");
    expect(md).toContain("## You");
    expect(md).toContain("## Assistant");
  });

  it("includes the user text and assistant answer", () => {
    expect(md).toContain("What is 2+2?");
    expect(md).toContain("It's **4**.");
  });

  it("collapses thinking and notes tool calls", () => {
    expect(md).toContain("<details><summary>Thinking</summary>");
    expect(md).toContain("🔧 Calculated: = 4");
  });

  it("embeds artifacts as fenced code with a version", () => {
    expect(md).toContain("**Artifact — Chart** (v2)");
    expect(md).toContain("```html");
    expect(md).toContain("<h1>4</h1>");
  });

  it("does not emit an Assistant heading for an empty turn", () => {
    const md2 = toMarkdown([{ role: "assistant", blocks: [] }]);
    expect(md2).not.toContain("## Assistant");
  });

  it("ends with a single trailing newline and no triple blank lines", () => {
    expect(md.endsWith("\n")).toBe(true);
    expect(md).not.toMatch(/\n{3,}/);
  });
});

describe("toJSON", () => {
  it("round-trips the messages inside an envelope", () => {
    const parsed = JSON.parse(toJSON(sample, "Math chat"));
    expect(parsed.title).toBe("Math chat");
    expect(parsed.exported_format).toBe("ocd.transcript.v1");
    expect(parsed.messages).toHaveLength(2);
    expect(parsed.messages[0].text).toBe("What is 2+2?");
  });
});

describe("exportSlug", () => {
  it("makes a filesystem-safe slug", () => {
    expect(exportSlug("My Chat: Revenue Q3!")).toBe("my-chat-revenue-q3");
    expect(exportSlug("")).toBe("conversation");
    expect(exportSlug("///")).toBe("conversation");
  });
});
