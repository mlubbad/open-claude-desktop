import { describe, expect, it } from "vitest";

import { fromBackend, toBackend } from "./persist";
import type { Message } from "./transcript";

const sample: Message[] = [
  { role: "user", text: "count rows" },
  {
    role: "assistant",
    blocks: [
      { kind: "thinking", phase: "plan", text: "I'll query it", elapsed: 2, streaming: false },
      {
        kind: "tool",
        id: "c1",
        name: "run_sql",
        input: "SELECT 1",
        labelRunning: "Querying",
        labelDone: "Queried",
        icon: "database",
        status: "done",
        summary: "1 row",
        table: { columns: ["n"], rows: [{ n: 1 }], total: 1, bytes: 8 },
      },
      { kind: "answer", text: "There is **1** row.", streaming: false },
      {
        kind: "artifact",
        doc: {
          id: "art1",
          title: "Chart",
          kind: "html",
          language: "",
          content: "<h1>1</h1>",
          version: 1,
          streaming: false,
        },
      },
    ],
  },
];

describe("transcript persistence", () => {
  it("round-trips a rich transcript losslessly", () => {
    const restored = fromBackend(toBackend(sample));
    expect(restored).toEqual(sample);
  });

  it("finalizes streaming flags on save", () => {
    const streaming: Message[] = [
      { role: "assistant", blocks: [{ kind: "answer", text: "partial", streaming: true }] },
    ];
    const stored = toBackend(streaming);
    const blocks = JSON.parse(stored[0].content);
    expect(blocks[0].streaming).toBe(false);
  });

  it("stores user + assistant with the backend shape", () => {
    const stored = toBackend(sample);
    expect(stored[0]).toEqual({ role: "user", content: "count rows", kind: "user" });
    expect(stored[1].role).toBe("assistant");
    expect(stored[1].kind).toBe("blocks");
  });

  it("loads a legacy plain assistant string as one answer block", () => {
    const restored = fromBackend([
      { role: "user", content: "hi", kind: "user" },
      { role: "assistant", content: "plain answer", kind: "final" },
    ]);
    expect(restored[1]).toEqual({
      role: "assistant",
      blocks: [{ kind: "answer", text: "plain answer", streaming: false }],
    });
  });

  it("survives corrupt block JSON by falling back to text", () => {
    const restored = fromBackend([{ role: "assistant", content: "{not json", kind: "blocks" }]);
    expect(restored[0].role).toBe("assistant");
    if (restored[0].role === "assistant") {
      expect(restored[0].blocks[0]).toEqual({ kind: "answer", text: "{not json", streaming: false });
    }
  });
});
