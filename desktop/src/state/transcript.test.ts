import { describe, expect, it } from "vitest";

import type { AgentEvent } from "../api/events";
import {
  answerQuestionState,
  answerText,
  applyEvent,
  type AssistantMessage,
  buildHistory,
  composeAnswers,
  contentAtVersion,
  editFrom,
  findArtifact,
  initialState,
  lastUserIndex,
  listArtifacts,
  type Message,
  resolveApprovalState,
  restoreApprovalState,
  retryFrom,
  setVersion,
  startTurn,
  type ToolCard,
  toolTrail,
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

  it("streams code_execution output and lists produced files on the tool card", () => {
    const s = drive([
      { type: "tool", id: "cx", name: "code_execution", input: "df.to_csv('out.csv')", label_running: "Running code", label_done: "Ran code", icon: "square-terminal" },
      { type: "tool_output_delta", id: "cx", stream: "stdout", text: "processing\n" },
      { type: "tool_output_delta", id: "cx", stream: "stdout", text: "wrote out.csv\n" },
      { type: "tool_result", id: "cx", name: "code_execution", summary: "ran ok · 1 file · local" },
      { type: "files", id: "cx", project: "general", items: [{ path: "out.csv", size: 42, kind: "csv" }] },
    ]);
    const tool = assistant(s).blocks.find((b) => b.kind === "tool") as ToolCard;
    expect(tool.status).toBe("done");
    expect(tool.output).toBe("processing\nwrote out.csv\n"); // deltas accumulate in order
    expect(tool.files).toEqual([{ path: "out.csv", size: 42, kind: "csv" }]);
    expect(tool.filesProject).toBe("general");
  });

  it("records the sign-in URL from the authenticate tool on the tool card", () => {
    const s = drive([
      { type: "tool", id: "au", name: "authenticate", input: "gcloud-adc", label_running: "Signing in connector", label_done: "Connector signed in", icon: "key" },
      { type: "tool_output_delta", id: "au", stream: "stderr", text: "Go to the following link:\n" },
      { type: "auth_url", id: "au", provider: "gcloud-adc", url: "https://accounts.google.com/o/oauth2/auth?x" },
    ]);
    const tool = assistant(s).blocks.find((b) => b.kind === "tool") as ToolCard;
    expect(tool.authUrl).toBe("https://accounts.google.com/o/oauth2/auth?x");
    expect(tool.status).toBe("running"); // still waiting on the browser consent
  });

  it("opens a produced CSV as a csv artifact in the side panel", () => {
    const s = drive([
      { type: "tool", id: "cx", name: "code_execution", input: "", label_running: "Running code", label_done: "Ran code", icon: "square-terminal" },
      { type: "tool_result", id: "cx", name: "code_execution", summary: "ran ok" },
      { type: "artifact_open", id: "cx::out.csv", title: "out.csv", kind: "csv", language: "csv" },
      { type: "artifact_delta", id: "cx::out.csv", text: "a,b\n1,2\n" },
      { type: "artifact_close", id: "cx::out.csv", version: 1 },
    ]);
    const arts = listArtifacts(s.messages);
    const csv = arts.find((a) => a.id === "cx::out.csv")!;
    expect(csv.kind).toBe("csv");
    expect(csv.content).toBe("a,b\n1,2\n");
    expect(s.openArtifactId).toBe("cx::out.csv");
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

  it("approving dismisses the prompt immediately and re-runs the tool card", () => {
    const s = drive([
      { type: "tool", id: "c1", name: "bash", input: "ls", label_running: "R", label_done: "R", icon: "terminal" },
      { type: "approval_required", turn_id: "t1", id: "c1", name: "bash", input: "ls" },
    ]);
    const after = resolveApprovalState(s, "approve");
    expect(after.pendingApproval).toBeNull();
    const tool = assistant(after).blocks.find((b) => b.kind === "tool") as ToolCard;
    expect(tool.status).toBe("running");
    // The backend's follow-up result still lands on the same card.
    const done = applyEvent(after, { type: "tool_result", id: "c1", name: "bash", summary: "3 files" });
    const t2 = assistant(done).blocks.find((b) => b.kind === "tool") as ToolCard;
    expect(t2.status).toBe("done");
  });

  it("declining dismisses the prompt and marks the tool declined", () => {
    const s = drive([
      { type: "tool", id: "c1", name: "bash", input: "ls", label_running: "R", label_done: "R", icon: "terminal" },
      { type: "approval_required", turn_id: "t1", id: "c1", name: "bash", input: "ls" },
    ]);
    const after = resolveApprovalState(s, "decline");
    expect(after.pendingApproval).toBeNull();
    const tool = assistant(after).blocks.find((b) => b.kind === "tool") as ToolCard;
    expect(tool.status).toBe("error");
    expect(tool.error).toMatch(/Declined/);
  });

  it("resolveApprovalState is a no-op without a pending approval", () => {
    const s = drive([{ type: "delta", scope: "answer", text: "hi" }]);
    expect(resolveApprovalState(s, "approve")).toBe(s);
  });

  it("a stale decision id never resolves a different pending approval", () => {
    const s = drive([
      { type: "tool", id: "c2", name: "bash", input: "ls", label_running: "R", label_done: "R", icon: "terminal" },
      { type: "approval_required", turn_id: "t1", id: "c2", name: "bash", input: "ls" },
    ]);
    // The user clicked the prompt for c1, but c2's approval replaced it meanwhile.
    expect(resolveApprovalState(s, "approve", "c1")).toBe(s);
    expect(resolveApprovalState(s, "approve", "c2").pendingApproval).toBeNull();
  });

  it("restoreApprovalState re-arms the prompt and the tool card after a failed reply", () => {
    const s = drive([
      { type: "tool", id: "c1", name: "bash", input: "ls", label_running: "R", label_done: "R", icon: "terminal" },
      { type: "approval_required", turn_id: "t1", id: "c1", name: "bash", input: "ls" },
    ]);
    const pending = s.pendingApproval!;
    const declined = resolveApprovalState(s, "decline", "c1");
    const restored = restoreApprovalState(declined, pending);
    expect(restored.pendingApproval).toEqual(pending);
    const tool = assistant(restored).blocks.find((b) => b.kind === "tool") as ToolCard;
    expect(tool.status).toBe("awaiting_approval");
    expect(tool.error).toBeUndefined();
  });

  it("tool_result clears an optimistically-planted decline error (exit_plan_mode path)", () => {
    const s = drive([
      { type: "tool", id: "c1", name: "exit_plan_mode", input: "{}", label_running: "R", label_done: "Planned", icon: "plan" },
      { type: "approval_required", turn_id: "t1", id: "c1", name: "exit_plan_mode", input: "{}" },
    ]);
    const declined = resolveApprovalState(s, "decline", "c1");
    const after = applyEvent(declined, { type: "tool_result", id: "c1", name: "exit_plan_mode", summary: "Kept planning" });
    const tool = assistant(after).blocks.find((b) => b.kind === "tool") as ToolCard;
    expect(tool.status).toBe("done");
    expect(tool.summary).toBe("Kept planning");
    expect(tool.error).toBeUndefined();
  });

  it("renders a question block and collapses it once answered", () => {
    const s = drive([
      {
        type: "question",
        id: "q1",
        questions: [
          { title: "Which channel?", options: ["A", "B"], allow_other: true },
          { title: "How long?", options: ["Short", "Long"] },
        ],
      },
    ]);
    const qb = assistant(s).blocks.find((b) => b.kind === "question");
    expect(qb && qb.kind === "question" && qb.questions.length).toBe(2);
    expect(qb && qb.kind === "question" && qb.answered).toBe(false);
    const after = answerQuestionState(s, "q1");
    const qb2 = assistant(after).blocks.find((b) => b.kind === "question");
    expect(qb2 && qb2.kind === "question" && qb2.answered).toBe(true);
  });

  it("composeAnswers builds a Q/A summary and drops skipped answers", () => {
    expect(
      composeAnswers([
        { question: "Which channel?", answer: "Better Creating" },
        { question: "How long?", answer: "  " },
      ]),
    ).toBe("Q: Which channel?\nA: Better Creating");
    expect(composeAnswers([{ question: "x", answer: "" }])).toBe("");
  });

  it("listArtifacts collects every artifact doc in order", () => {
    const s = drive([
      { type: "artifact_open", id: "a1", title: "One", kind: "html", language: "" },
      { type: "artifact_close", id: "a1", version: 1 },
      { type: "artifact_open", id: "a2", title: "Two", kind: "markdown", language: "" },
      { type: "artifact_close", id: "a2", version: 1 },
      { type: "done" },
    ]);
    expect(listArtifacts(s.messages).map((d) => d.id)).toEqual(["a1", "a2"]);
  });

  it("stores usage from the usage event", () => {
    const s = drive([
      { type: "delta", scope: "answer", text: "hi" },
      {
        type: "usage",
        model: "gpt-4o",
        context_tokens: 1200,
        output_tokens: 40,
        context_limit: 128000,
        context_pct: 1,
        cost_usd: 0.003,
      },
      { type: "done" },
    ]);
    expect(s.usage).toEqual({
      model: "gpt-4o",
      context_tokens: 1200,
      output_tokens: 40,
      context_limit: 128000,
      context_pct: 1,
      cost_usd: 0.003,
    });
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

  it("streams an artifact open/delta/close and opens the panel", () => {
    const s = drive([
      { type: "artifact_open", id: "art1", title: "Page", kind: "html", language: "" },
      { type: "artifact_delta", id: "art1", text: "<h1>" },
      { type: "artifact_delta", id: "art1", text: "hi</h1>" },
      { type: "artifact_close", id: "art1", version: 1 },
    ]);
    expect(s.openArtifactId).toBe("art1");
    const doc = findArtifact(s, "art1")!;
    expect(doc.content).toBe("<h1>hi</h1>");
    expect(doc.version).toBe(1);
    expect(doc.streaming).toBe(false);
    // The assistant message carries an artifact block referencing it.
    const a = assistant(s);
    expect(a.blocks.some((b) => b.kind === "artifact")).toBe(true);
  });

  it("update_artifact (same id) replaces content and bumps version without duplicating", () => {
    const s = drive([
      { type: "artifact_open", id: "art1", title: "Doc", kind: "markdown", language: "" },
      { type: "artifact_delta", id: "art1", text: "v1 body" },
      { type: "artifact_close", id: "art1", version: 1 },
      { type: "artifact_open", id: "art1", title: "Doc", kind: "markdown", language: "" },
      { type: "artifact_delta", id: "art1", text: "v2 body" },
      { type: "artifact_close", id: "art1", version: 2 },
    ]);
    const doc = findArtifact(s, "art1")!;
    expect(doc.content).toBe("v2 body");
    expect(doc.version).toBe(2);
    const artifactBlocks = assistant(s).blocks.filter((b) => b.kind === "artifact");
    expect(artifactBlocks).toHaveLength(1); // upsert, not duplicate
  });

  it("accumulates each finalized version's content in history", () => {
    const s = drive([
      { type: "artifact_open", id: "art1", title: "Doc", kind: "markdown", language: "" },
      { type: "artifact_delta", id: "art1", text: "v1 body" },
      { type: "artifact_close", id: "art1", version: 1 },
      { type: "artifact_open", id: "art1", title: "Doc", kind: "markdown", language: "" },
      { type: "artifact_delta", id: "art1", text: "v2 body" },
      { type: "artifact_close", id: "art1", version: 2 },
    ]);
    const doc = findArtifact(s, "art1")!;
    expect(doc.versions).toEqual(["v1 body", "v2 body"]);
    // The live content is the newest; older versions are recoverable.
    expect(contentAtVersion(doc, 1)).toBe("v1 body");
    expect(contentAtVersion(doc, 2)).toBe("v2 body");
  });

  it("a streamed update (empty kind/language) preserves the existing fields", () => {
    const s = drive([
      { type: "artifact_open", id: "art1", title: "Chart", kind: "html", language: "" },
      { type: "artifact_delta", id: "art1", text: "<h1>1</h1>" },
      { type: "artifact_close", id: "art1", version: 1 },
      // A live-streamed update omits kind/title (empty) — must keep them.
      { type: "artifact_open", id: "art1", title: "", kind: "", language: "" },
      { type: "artifact_delta", id: "art1", text: "<h1>2</h1>" },
      { type: "artifact_close", id: "art1", version: 2 },
    ]);
    const doc = findArtifact(s, "art1")!;
    expect(doc.kind).toBe("html"); // preserved
    expect(doc.title).toBe("Chart"); // preserved
    expect(doc.content).toBe("<h1>2</h1>");
    expect(doc.version).toBe(2);
  });

  it("setVersion writes at a 1-based slot and pads gaps", () => {
    expect(setVersion([], 1, "a")).toEqual(["a"]);
    expect(setVersion(["a"], 2, "b")).toEqual(["a", "b"]);
    expect(setVersion(["a"], 3, "c")).toEqual(["a", "", "c"]);
    // overwrite in place
    expect(setVersion(["a", "b"], 1, "z")).toEqual(["z", "b"]);
  });

  it("contentAtVersion tolerates a legacy doc without a versions array", () => {
    const legacy = {
      id: "x", title: "t", kind: "markdown" as const, language: "",
      content: "live", version: 1, streaming: false,
    } as unknown as Parameters<typeof contentAtVersion>[0];
    expect(contentAtVersion(legacy, 1)).toBe("live");
  });

  it("editFrom replaces a user message and drops everything after it", () => {
    const msgs: Message[] = [
      { role: "user", text: "q1" },
      { role: "assistant", blocks: [{ kind: "answer", text: "a1", streaming: false }] },
      { role: "user", text: "q2" },
      { role: "assistant", blocks: [{ kind: "answer", text: "a2", streaming: false }] },
    ];
    const s = editFrom({ ...initialState(), messages: msgs }, 2, "q2-edited");
    // Keeps q1/a1, replaces q2, drops a2, opens a fresh assistant.
    expect(s.messages).toHaveLength(4);
    expect(s.messages[2]).toEqual({ role: "user", text: "q2-edited" });
    expect(s.messages[3]).toEqual({ role: "assistant", blocks: [] });
    expect(s.running).toBe(true);
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

// The tool-activity trail carried in history: a turn that ended before a full answer
// (step limit, stream drop) must still tell the model what was already gathered, so
// "continue" resumes the work instead of restarting it from zero.
describe("toolTrail + buildHistory digest", () => {
  const tool = (over: Partial<ToolCard>): ToolCard => ({
    kind: "tool",
    id: "t1",
    name: "browser_navigate",
    input: "https://example.com",
    labelRunning: "Browsing",
    labelDone: "Browsed",
    icon: "🌐",
    status: "done",
    ...over,
  });

  it("digests tool cards into name(input) → outcome lines", () => {
    const m: AssistantMessage = {
      role: "assistant",
      blocks: [
        tool({ id: "a", name: "Scrape", input: "https://x.com", summary: "HTTP 403" }),
        tool({ id: "b", name: "Click", input: "loc=[0,0]", error: "loc must be a list" }),
        { kind: "answer", text: "partial", streaming: false },
      ],
    };
    const trail = toolTrail(m);
    expect(trail).toContain("Scrape(https://x.com) → HTTP 403");
    expect(trail).toContain("Click(loc=[0,0]) → ERROR: loc must be a list");
  });

  it("caps the trail and reports what it omitted", () => {
    const blocks = Array.from({ length: 20 }, (_, i) =>
      tool({ id: `t${i}`, name: `tool${i}`, summary: "ok" }),
    );
    const trail = toolTrail({ role: "assistant", blocks });
    expect(trail).toContain("…8 earlier calls omitted");
    expect(trail).not.toContain("tool0(");
    expect(trail).toContain("tool19(");
  });

  it("buildHistory prepends the trail so an answerless turn still contributes", () => {
    const msgs: Message[] = [
      { role: "user", text: "audit the site" },
      {
        role: "assistant",
        blocks: [tool({ id: "a", name: "Scrape", input: "https://x.com", summary: "HTTP 403" })],
      },
    ];
    const h = buildHistory(msgs);
    expect(h[1].content).toContain("Scrape(https://x.com) → HTTP 403");
  });

  it("buildHistory without tool cards is unchanged (answer only)", () => {
    const msgs: Message[] = [
      { role: "user", text: "q1" },
      { role: "assistant", blocks: [{ kind: "answer", text: "a1", streaming: false }] },
    ];
    expect(buildHistory(msgs)[1]).toEqual({ role: "assistant", content: "a1", kind: "final" });
  });
});

describe("image attachments on user turns", () => {
  it("startTurn stores images on the user message (and omits the key when none)", () => {
    const withImgs = startTurn(initialState(), "look", ["data:image/png;base64,AA"]);
    expect((withImgs.messages[0] as { images?: string[] }).images).toEqual([
      "data:image/png;base64,AA",
    ]);
    const plain = startTurn(initialState(), "hi");
    expect("images" in (plain.messages[0] as object)).toBe(false);
  });

  it("buildHistory stays text-only — images ride only the turn they were sent on", () => {
    const s = startTurn(initialState(), "look", ["data:image/png;base64,AA"]);
    const hist = buildHistory(s.messages);
    expect(hist[0]).toEqual({ role: "user", content: "look", kind: "user" });
  });
});
