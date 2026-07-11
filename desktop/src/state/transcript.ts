// Pure transcript reducer: folds the backend's SSE event stream into a renderable
// message list. Framework-free and deterministic so it can be unit-tested and reused
// by any UI. This is the TypeScript port of the Reflex state machine's streaming
// semantics: thinking-block coalescing with elapsed labels, answer streaming,
// per-call tool cards upserted by id, sources, and HITL approval prompts.

import type { AgentEvent, ArtifactKind, ProducedFile, Source, Usage } from "../api/events";

export interface ArtifactDoc {
  id: string;
  title: string;
  kind: ArtifactKind;
  language: string;
  content: string;
  version: number;
  streaming: boolean;
  // Finalized content of every version, 1-indexed by position (versions[0] is v1).
  // Lets the panel navigate revisions the way Claude Desktop does.
  versions: string[];
}

export interface ArtifactBlock {
  kind: "artifact";
  doc: ArtifactDoc;
}

export type ToolStatus = "running" | "done" | "error" | "awaiting_approval";

export interface ToolCard {
  kind: "tool";
  id: string;
  name: string;
  input: string;
  labelRunning: string;
  labelDone: string;
  icon: string;
  status: ToolStatus;
  summary?: string;
  error?: string;
  table?: { columns: string[]; rows: Record<string, unknown>[]; total: number; bytes: number };
  sources?: Source[];
  // Live-streamed stdout/stderr from a code_execution run.
  output?: string;
  // Files the run produced (workspace-relative) + the project they live under (download).
  files?: ProducedFile[];
  filesProject?: string;
  // A sign-in URL surfaced by the `authenticate` tool (open in a browser to consent).
  authUrl?: string;
}

export interface ThinkingBlock {
  kind: "thinking";
  phase: string;
  text: string;
  elapsed?: number;
  streaming: boolean;
}

export interface AnswerBlock {
  kind: "answer";
  text: string;
  streaming: boolean;
}

export interface QuestionItem {
  title: string;
  options: string[];
  allowOther: boolean;
}

// An inline structured-question card the agent raised mid-turn (contract §5.1).
// `answered` collapses the card once the user responds; the answer is posted as the
// next user turn by the caller.
export interface QuestionBlock {
  kind: "question";
  id: string;
  questions: QuestionItem[];
  answered: boolean;
}

export type Block = ThinkingBlock | AnswerBlock | ToolCard | ArtifactBlock | QuestionBlock;

export interface AssistantMessage {
  role: "assistant";
  blocks: Block[];
}

export interface UserMessage {
  role: "user";
  text: string;
}

export type Message = UserMessage | AssistantMessage;

export interface TranscriptState {
  messages: Message[];
  turnId: string | null;
  running: boolean;
  // A pending HITL approval the UI should surface (null when none).
  pendingApproval: { turnId: string; toolCallId: string; name: string; input: string } | null;
  // The artifact id currently shown in the side panel (null = panel closed).
  openArtifactId: string | null;
  // Token/cost usage from the most recent completed turn (null until one finishes).
  usage: Usage | null;
  error: string | null;
}

export function initialState(): TranscriptState {
  return {
    messages: [],
    turnId: null,
    running: false,
    pendingApproval: null,
    openArtifactId: null,
    usage: null,
    error: null,
  };
}

// Every artifact document in the transcript, in creation order (for the info rail).
export function listArtifacts(messages: Message[]): ArtifactDoc[] {
  const out: ArtifactDoc[] = [];
  for (const m of messages) {
    if (m.role !== "assistant") continue;
    for (const b of m.blocks) {
      if (b.kind === "artifact") out.push(b.doc);
    }
  }
  return out;
}

// Find the artifact document for a given id anywhere in the transcript.
export function findArtifact(state: TranscriptState, id: string | null): ArtifactDoc | null {
  if (!id) return null;
  for (const m of state.messages) {
    if (m.role !== "assistant") continue;
    for (const b of m.blocks) {
      if (b.kind === "artifact" && b.doc.id === id) return b.doc;
    }
  }
  return null;
}

// Replace the whole transcript (loading a saved conversation).
export function loadMessages(messages: Message[]): TranscriptState {
  return { ...initialState(), messages };
}

// The concatenated answer text of an assistant message (for copy + history).
export function answerText(m: AssistantMessage): string {
  return m.blocks
    .filter((b): b is AnswerBlock => b.kind === "answer")
    .map((b) => b.text)
    .join("\n")
    .trim();
}

// Index of the most recent user message, or -1.
export function lastUserIndex(messages: Message[]): number {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i].role === "user") return i;
  }
  return -1;
}

export interface HistoryTurn {
  role: string;
  content: string;
  kind: string;
}

// One-line-per-call digest of a turn's tool activity (name, input, outcome), carried
// in history so a follow-up ("continue", "try again") builds on what was already
// gathered instead of redoing every call — matching Claude Desktop, where prior tool
// use stays visible to the model for the rest of the conversation. Tightly capped:
// the digest is a trail marker, not a transcript.
const TRAIL_MAX_TOOLS = 12;
const TRAIL_MAX_LINE = 160;

export function toolTrail(m: AssistantMessage): string {
  const cards = m.blocks.filter((b): b is ToolCard => b.kind === "tool");
  if (cards.length === 0) return "";
  const lines = cards.slice(-TRAIL_MAX_TOOLS).map((c) => {
    const outcome = c.error ? `ERROR: ${c.error}` : c.summary || c.status;
    return `${c.name}(${c.input}) → ${outcome}`.slice(0, TRAIL_MAX_LINE);
  });
  const omitted = cards.length - lines.length;
  const head = omitted > 0 ? `…${omitted} earlier calls omitted; ` : "";
  return `[Tool activity this turn: ${head}${lines.join("; ")}]`;
}

// Reconstruct the (role, content) history the backend expects from prior messages.
// Assistant turns carry the tool trail alongside the answer text: without it, a turn
// that ended before a full answer (step limit, stream drop) contributed NOTHING to
// the next turn, so "continue" restarted the work from zero — and hit the same wall.
export function buildHistory(messages: Message[]): HistoryTurn[] {
  return messages.map((m) => {
    if (m.role === "user") return { role: "user", content: m.text, kind: "user" };
    const content = [toolTrail(m), answerText(m)].filter(Boolean).join("\n\n");
    return { role: "assistant", content, kind: "final" };
  });
}

// Truncate to just after the last user message and append a fresh assistant slot
// (used to regenerate the last response).
export function retryFrom(state: TranscriptState, userIdx: number): TranscriptState {
  const kept = state.messages.slice(0, userIdx + 1);
  return {
    ...state,
    running: true,
    error: null,
    pendingApproval: null,
    messages: [...kept, { role: "assistant", blocks: [] }],
  };
}

// Replace a user message at `index` with edited text, drop everything after it, and
// open a fresh assistant slot (edit-and-resend / branch).
export function editFrom(state: TranscriptState, index: number, text: string): TranscriptState {
  const kept = state.messages.slice(0, index);
  return {
    ...state,
    running: true,
    error: null,
    pendingApproval: null,
    messages: [...kept, { role: "user", text }, { role: "assistant", blocks: [] }],
  };
}

// Begin a new user turn: append the user message + a fresh assistant message.
export function startTurn(state: TranscriptState, goal: string): TranscriptState {
  return {
    ...state,
    running: true,
    error: null,
    pendingApproval: null,
    messages: [
      ...state.messages,
      { role: "user", text: goal },
      { role: "assistant", blocks: [] },
    ],
  };
}

function currentAssistant(state: TranscriptState): AssistantMessage {
  for (let i = state.messages.length - 1; i >= 0; i--) {
    const m = state.messages[i];
    if (m.role === "assistant") return m;
  }
  const created: AssistantMessage = { role: "assistant", blocks: [] };
  state.messages.push(created);
  return created;
}

function lastBlock(a: AssistantMessage): Block | undefined {
  return a.blocks[a.blocks.length - 1];
}

// Apply one event, returning a NEW state (immutably at the top level; blocks are
// cloned on the touched assistant message so React sees a changed reference).
export function applyEvent(prev: TranscriptState, ev: AgentEvent): TranscriptState {
  const state: TranscriptState = { ...prev, messages: prev.messages.slice() };
  const idx = state.messages.length - 1;
  // Ensure the tail is a mutable assistant message we can push blocks onto.
  if (idx >= 0 && state.messages[idx].role === "assistant") {
    const a = state.messages[idx] as AssistantMessage;
    state.messages[idx] = { role: "assistant", blocks: a.blocks.slice() };
  }
  const assistant = currentAssistant(state);

  switch (ev.type) {
    case "turn_start":
      return { ...state, turnId: ev.turn_id, running: true };

    case "think_open": {
      assistant.blocks.push({ kind: "thinking", phase: ev.phase, text: "", streaming: true });
      return state;
    }

    case "think_close": {
      // Close the most recent streaming thinking block.
      for (let i = assistant.blocks.length - 1; i >= 0; i--) {
        const b = assistant.blocks[i];
        if (b.kind === "thinking" && b.streaming) {
          assistant.blocks[i] = { ...b, streaming: false, elapsed: ev.elapsed };
          break;
        }
      }
      return state;
    }

    case "answer_open": {
      const lb = lastBlock(assistant);
      if (!(lb && lb.kind === "answer" && lb.streaming)) {
        assistant.blocks.push({ kind: "answer", text: "", streaming: true });
      }
      return state;
    }

    case "answer_to_think": {
      // The streamed answer was actually narration; fold it back into a think block.
      const lb = lastBlock(assistant);
      if (lb && lb.kind === "answer") {
        const folded: ThinkingBlock = {
          kind: "thinking",
          phase: ev.phase,
          text: lb.text,
          elapsed: ev.elapsed,
          streaming: false,
        };
        assistant.blocks[assistant.blocks.length - 1] = folded;
      }
      return state;
    }

    case "delta": {
      if (ev.scope === "think") {
        const lb = lastBlock(assistant);
        if (lb && lb.kind === "thinking" && lb.streaming) {
          assistant.blocks[assistant.blocks.length - 1] = { ...lb, text: lb.text + ev.text };
        } else {
          assistant.blocks.push({ kind: "thinking", phase: "", text: ev.text, streaming: true });
        }
      } else {
        const lb = lastBlock(assistant);
        if (lb && lb.kind === "answer") {
          assistant.blocks[assistant.blocks.length - 1] = { ...lb, text: lb.text + ev.text };
        } else {
          assistant.blocks.push({ kind: "answer", text: ev.text, streaming: true });
        }
      }
      return state;
    }

    case "tool": {
      assistant.blocks.push({
        kind: "tool",
        id: ev.id,
        name: ev.name,
        input: ev.input,
        labelRunning: ev.label_running,
        labelDone: ev.label_done,
        icon: ev.icon,
        status: "running",
      });
      return state;
    }

    case "tool_result":
      // Clear any optimistically-planted error (e.g. a declined exit_plan_mode
      // resolves as a successful "kept planning" result, not an error).
      return updateTool(state, assistant, ev.id, (t) => ({ ...t, status: "done", summary: ev.summary, error: undefined }));

    case "tool_error":
      return updateTool(state, assistant, ev.id, (t) => ({ ...t, status: "error", error: ev.text }));

    case "tool_output_delta":
      // Append live stdout/stderr to the tool card's running log (streams as it prints).
      return updateTool(state, assistant, ev.id, (t) => ({ ...t, output: (t.output ?? "") + ev.text }));

    case "auth_url":
      // The `authenticate` tool surfaced a sign-in URL — record it on the tool card so
      // the UI shows an "open sign-in" affordance (the app also opens it automatically).
      return updateTool(state, assistant, ev.id, (t) => ({ ...t, authUrl: ev.url }));

    case "files":
      return updateTool(state, assistant, ev.id, (t) => ({ ...t, files: ev.items, filesProject: ev.project }));

    case "table":
      return updateTool(state, assistant, ev.id, (t) => ({
        ...t,
        status: t.status === "error" ? "error" : "done",
        table: { columns: ev.columns, rows: ev.rows, total: ev.total, bytes: ev.bytes },
      }));

    case "sources":
      return updateTool(state, assistant, ev.id, (t) => ({ ...t, sources: ev.items }));

    case "artifact_open": {
      if (findArtifact(state, ev.id)) {
        // An update: reset the live content for the incoming new version. Prior
        // versions stay in `versions` (each was recorded on its artifact_close). A
        // streamed update omits kind/language/title (empty) — keep the existing values.
        const s2 = mutateArtifact(state, ev.id, (d) => ({
          ...d,
          title: ev.title || d.title,
          kind: ev.kind || d.kind,
          language: ev.language || d.language,
          content: "",
          streaming: true,
        }));
        return { ...s2, openArtifactId: ev.id };
      }
      assistant.blocks.push({
        kind: "artifact",
        doc: {
          id: ev.id,
          title: ev.title,
          kind: ev.kind || "markdown", // a new artifact always has a kind; "" only on updates
          language: ev.language,
          content: "",
          version: 0,
          streaming: true,
          versions: [],
        },
      });
      return { ...state, openArtifactId: ev.id };
    }

    case "artifact_delta":
      return mutateArtifact(state, ev.id, (d) => ({ ...d, content: d.content + ev.text }));

    case "artifact_close":
      // Finalize: stamp the version number and snapshot the completed content so it
      // can be revisited even after later revisions overwrite the live content.
      return mutateArtifact(state, ev.id, (d) => ({
        ...d,
        streaming: false,
        version: ev.version,
        versions: setVersion(d.versions, ev.version, d.content),
      }));

    case "approval_required": {
      updateTool(state, assistant, ev.id, (t) => ({ ...t, status: "awaiting_approval" }));
      return {
        ...state,
        pendingApproval: {
          turnId: ev.turn_id,
          toolCallId: ev.id,
          name: ev.name,
          input: ev.input,
        },
      };
    }

    case "question": {
      assistant.blocks.push({
        kind: "question",
        id: ev.id,
        questions: ev.questions.map((q) => ({
          title: q.title,
          options: q.options,
          allowOther: q.allow_other ?? true,
        })),
        answered: false,
      });
      return state;
    }

    case "usage":
      return {
        ...state,
        usage: {
          model: ev.model,
          context_tokens: ev.context_tokens,
          output_tokens: ev.output_tokens,
          context_limit: ev.context_limit,
          context_pct: ev.context_pct,
          cost_usd: ev.cost_usd,
        },
      };

    case "error":
      return { ...state, error: ev.text, running: false };

    case "done": {
      // Finalize any still-streaming blocks.
      assistant.blocks = assistant.blocks.map((b) =>
        (b.kind === "answer" || b.kind === "thinking") && b.streaming ? { ...b, streaming: false } : b,
      );
      return { ...state, running: false, pendingApproval: null };
    }

    default:
      return state;
  }
}

// Mark a question card answered (collapses it) once the user responds. Immutable.
export function answerQuestionState(state: TranscriptState, id: string): TranscriptState {
  const messages = state.messages.map((m) => {
    if (m.role !== "assistant") return m;
    let changed = false;
    const blocks = m.blocks.map((b) => {
      if (b.kind === "question" && b.id === id && !b.answered) {
        changed = true;
        return { ...b, answered: true };
      }
      return b;
    });
    return changed ? { role: "assistant" as const, blocks } : m;
  });
  return { ...state, messages };
}

// Compose the user-facing answer text from a set of (question, answer) pairs — the
// "Q: …\nA: …" summary that becomes the next user turn (contract §5.1). Blank answers
// (skipped) are omitted; if everything is blank the result is empty.
export function composeAnswers(pairs: { question: string; answer: string }[]): string {
  return pairs
    .filter((p) => p.answer.trim())
    .map((p) => `Q: ${p.question}\nA: ${p.answer.trim()}`)
    .join("\n\n");
}

// Optimistically resolve the pending HITL approval: the prompt disappears the moment
// the user decides (the backend confirms via its own follow-up events). Approving
// flips the tool card back to "running"; declining marks it declined immediately —
// the backend's tool_result/tool_error for the same id refines it either way.
// `toolCallId` pins the decision to the approval the user actually saw, so a
// just-arrived different approval is never resolved by a stale click.
export function resolveApprovalState(
  state: TranscriptState,
  decision: "approve" | "decline",
  toolCallId?: string,
): TranscriptState {
  const pending = state.pendingApproval;
  if (!pending) return state;
  if (toolCallId !== undefined && pending.toolCallId !== toolCallId) return state;
  const messages = state.messages.map((m) => {
    if (m.role !== "assistant") return m;
    let changed = false;
    const blocks = m.blocks.map((b) => {
      if (b.kind === "tool" && b.id === pending.toolCallId && b.status === "awaiting_approval") {
        changed = true;
        return decision === "approve"
          ? { ...b, status: "running" as const }
          : { ...b, status: "error" as const, error: "Declined — the tool was not run." };
      }
      return b;
    });
    return changed ? { role: "assistant" as const, blocks } : m;
  });
  return { ...state, messages, pendingApproval: null };
}

// Re-arm an approval whose delivery to the backend failed: the prompt comes back and
// the tool card returns to awaiting, so the user can decide again instead of the
// backend timing the request out as a silent decline.
export function restoreApprovalState(
  state: TranscriptState,
  pending: NonNullable<TranscriptState["pendingApproval"]>,
): TranscriptState {
  const messages = state.messages.map((m) => {
    if (m.role !== "assistant") return m;
    let changed = false;
    const blocks = m.blocks.map((b) => {
      if (b.kind === "tool" && b.id === pending.toolCallId && (b.status === "running" || b.status === "error")) {
        changed = true;
        return { ...b, status: "awaiting_approval" as const, error: undefined };
      }
      return b;
    });
    return changed ? { role: "assistant" as const, blocks } : m;
  });
  return { ...state, messages, pendingApproval: pending };
}

function updateTool(
  state: TranscriptState,
  assistant: AssistantMessage,
  id: string,
  fn: (t: ToolCard) => ToolCard,
): TranscriptState {
  for (let i = assistant.blocks.length - 1; i >= 0; i--) {
    const b = assistant.blocks[i];
    if (b.kind === "tool" && b.id === id) {
      assistant.blocks[i] = fn(b);
      break;
    }
  }
  return state;
}

// Record a finalized version's content at its 1-based slot, growing the list (with
// "" placeholders) if a version number arrives out of order. Pure + immutable.
export function setVersion(versions: string[], version: number, content: string): string[] {
  const out = versions.slice();
  const idx = Math.max(0, version - 1);
  while (out.length <= idx) out.push("");
  out[idx] = content;
  return out;
}

// The content to show for a given 1-based version. The newest/live content lives in
// `doc.content`; older finalized versions live in `doc.versions`.
export function contentAtVersion(doc: ArtifactDoc, version: number): string {
  if (version >= doc.version) return doc.content;
  return (doc.versions ?? [])[version - 1] ?? doc.content;
}

// Immutably update the artifact doc with the given id wherever it lives.
function mutateArtifact(
  state: TranscriptState,
  id: string,
  fn: (d: ArtifactDoc) => ArtifactDoc,
): TranscriptState {
  const messages = state.messages.map((m) => {
    if (m.role !== "assistant") return m;
    let changed = false;
    const blocks = m.blocks.map((b) => {
      if (b.kind === "artifact" && b.doc.id === id) {
        changed = true;
        return { ...b, doc: fn(b.doc) };
      }
      return b;
    });
    return changed ? { role: "assistant" as const, blocks } : m;
  });
  return { ...state, messages };
}
