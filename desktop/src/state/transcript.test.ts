import { describe, expect, it } from "vitest";

import type { AgentEvent } from "../api/events";
import {
  answerText,
  applyEvent,
  type AssistantMessage,
  buildHistory,
  initialState,
  lastUserIndex,
  type Message,
  retryFrom,
  startTurn,
  type ToolCard,
  type TranscriptState,
} from "./transcript";

function drive(events: AgentEvent[], goal = "hi"): TranscriptState {
  let s = startTurn(initialState(), goal);
  for (const ev of events) s = applyEvent(s, ev);
  return s;
}

function assistant(s: TranscriptState): AssistantMessage {
  return s.messages.find((m) => m.role === "assistant") as AssistantMessage;
}

describe("transcript reducer", () => {
  it("streams a thinking block then an answer", () => {
    const s = drive([
      { type: "turn_start", turn_id: "t1" },
      { type: "think_open", phase: "plan" },
      { type: "delta", scope: "think", text: "let me plan " },
      { type: "delta", scope: "think", text: "the steps" },
      { type: "think_close", elapsed: 2 },
      { type: "answer_open" },
      { type: "delta", scope: "answer", text: "Hello" },
      { type: "delta", scope: "answer", text: " world" },
      { type: "done" },
    ]);
    expect(s.turnId).toBe("t1");
    expect(s.running).toBe(false);
    const blocks = assistant(s).blocks;
    const think = blocks.find((b) => b.kind === "thinking")!;
    expect(think.kind === "thinking" && think.text).toBe("let me plan the steps");
    expect(think.kind === "thinking" && think.elapsed).toBe(2);
    expect(think.kind === "thinking" && think.streaming).toBe(false);
    const ans = blocks.find((b) => b.kind === "answer")!;
    expect(ans.kind === "answer" && ans.text).toBe("Hello world");
    expect(ans.kind === "answer" && ans.streaming).toBe(false);
  });

  it("upserts a tool card by id through running -> result -> table", () => {
    const s = drive([
      { type: "tool", id: "c1", name: "run_sql", input: "SELECT 1", label_running: "Querying", label_done: "Queried", icon: "database" },
      { type: "tool_result", id: "c1", name: "run_sql", summary: "1 row" },
      { type: "table", id: "c1", columns: ["n"], rows: [{ n: 1 }], total: 1, bytes: 8 },
    ]);
    const tools = assistant(s).blocks.filter((b) => b.kind === "tool") as ToolCard[];
    expect(tools).toHaveLength(1);
    expect(tools[0].status).toBe("done");
    expect(tools[0].summary).toBe("1 row");
    expect(tools[0].table?.rows).toEqual([{ n: 1 }]);
  });

  it("marks a tool card errored", () => {
    const s = drive([
      { type: "tool", id: "c1", name: "bash", input: "ls", label_running: "Running", label_done: "Ran", icon: "terminal" },
      { type: "tool_error", id: "c1", name: "bash", text: "boom" },
    ]);
    const tool = assistant(s).blocks.find((b) => b.kind === "tool") as ToolCard;
    expect(tool.status).toBe("error");
    expect(tool.error).toBe("boom");
  });

  it("folds a pre-tool narration answer back into a thinking block", () => {
    const s = drive([
      { type: "answer_open" },
      { type: "delta", scope: "answer", text: "I'll look this up." },
      { type: "answer_to_think", phase: "narration", elapsed: 1 },
    ]);
    const blocks = assistant(s).blocks;
    expect(blocks.some((b) => b.kind === "answer")).toBe(false);
    const think = blocks.find((b) => b.kind === "thinking")!;
    expect(think.kind === "thinking" && think.text).toBe("I'll look this up.");
  });

  it("surfaces a HITL approval prompt and marks the tool awaiting", () => {
    const s = drive([
      { type: "tool", id: "c1", name: "bash", input: "rm x", label_running: "Running", label_done: "Ran", icon: "terminal" },
      { type: "approval_required", turn_id: "t1", id: "c1", name: "bash", input: "rm x" },
    ]);
    expect(s.pendingApproval).toEqual({ turnId: "t1", toolCallId: "c1", name: "bash", input: "rm x" });
    const tool = assistant(s).blocks.find((b) => b.kind === "tool") as ToolCard;
    expect(tool.status).toBe("awaiting_approval");
  });

  it("clears the pending approval on done", () => {
    const s = drive([
      { type: "tool", id: "c1", name: "bash", input: "ls", label_running: "R", label_done: "R", icon: "terminal" },
      { type: "approval_required", turn_id: "t1", id: "c1", name: "bash", input: "ls" },
      { type: "done" },
    ]);
    expect(s.pendingApproval).toBeNull();
  });

  it("records an error event", () => {
    const s = drive([{ type: "error", text: "no API key for OpenAI" }]);
    expect(s.error).toBe("no API key for OpenAI");
    expect(s.running).toBe(false);
  });

  it("answerText joins only answer blocks", () => {
    const a: AssistantMessage = {
      role: "assistant",
      blocks: [
        { kind: "thinking", phase: "", text: "hmm", streaming: false },
        { kind: "answer", text: "line 1", streaming: false },
        { kind: "answer", text: "line 2", streaming: false },
      ],
    };
    expect(answerText(a)).toBe("line 1\nline 2");
  });

  it("buildHistory maps user + assistant to role/content", () => {
    const msgs: Message[] = [
      { role: "user", text: "q1" },
      { role: "assistant", blocks: [{ kind: "answer", text: "a1", streaming: false }] },
    ];
    expect(buildHistory(msgs)).toEqual([
      { role: "user", content: "q1", kind: "user" },
      { role: "assistant", content: "a1", kind: "final" },
    ]);
  });

  it("lastUserIndex + retryFrom truncate to the last user for regeneration", () => {
    const msgs: Message[] = [
      { role: "user", text: "q1" },
      { role: "assistant", blocks: [{ kind: "answer", text: "old", streaming: false }] },
    ];
    const idx = lastUserIndex(msgs);
    expect(idx).toBe(0);
    const s = retryFrom({ ...initialState(), messages: msgs }, idx);
    // Keeps the user message, drops the old answer, opens a fresh assistant slot.
    expect(s.messages).toHaveLength(2);
    expect(s.messages[0]).toEqual({ role: "user", text: "q1" });
    expect(s.messages[1]).toEqual({ role: "assistant", blocks: [] });
    expect(s.running).toBe(true);
  });

  it("keeps prior messages immutable across turns", () => {
    let s = drive([{ type: "delta", scope: "answer", text: "first" }, { type: "done" }]);
    const firstAssistant = assistant(s);
    s = startTurn(s, "again");
    s = applyEvent(s, { type: "delta", scope: "answer", text: "second" });
    // The first assistant message object is untouched by the second turn.
    const firstAns = firstAssistant.blocks.find((b) => b.kind === "answer");
    expect(firstAns && firstAns.kind === "answer" && firstAns.text).toBe("first");
    expect(s.messages.filter((m) => m.role === "user")).toHaveLength(2);
  });
});
