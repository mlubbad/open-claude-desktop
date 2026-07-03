// Pure transcript reducer: folds the backend's SSE event stream into a renderable
// message list. Framework-free and deterministic so it can be unit-tested and reused
// by any UI. This is the TypeScript port of the Reflex state machine's streaming
// semantics: thinking-block coalescing with elapsed labels, answer streaming,
// per-call tool cards upserted by id, sources, and HITL approval prompts.

import type { AgentEvent, ArtifactKind, Source, Usage } from "../api/events";

export interface ArtifactDoc {
  id: string;
  title: string;
  kind: ArtifactKind;
  language: string;
  content: string;
  version: number;
  streaming: boolean;
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

export type Block = ThinkingBlock | AnswerBlock | ToolCard | ArtifactBlock;

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

// Reconstruct the (role, content) history the backend expects from prior messages.
export function buildHistory(messages: Message[]): HistoryTurn[] {
  return messages.map((m) =>
    m.role === "user"
      ? { role: "user", content: m.text, kind: "user" }
      : { role: "assistant", content: answerText(m), kind: "final" },
  );
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
      return updateTool(state, assistant, ev.id, (t) => ({ ...t, status: "done", summary: ev.summary }));

    case "tool_error":
      return updateTool(state, assistant, ev.id, (t) => ({ ...t, status: "error", error: ev.text }));

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
        // An update: reset content for the incoming new version.
        const s2 = mutateArtifact(state, ev.id, (d) => ({
          ...d,
          title: ev.title,
          kind: ev.kind,
          language: ev.language,
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
          kind: ev.kind,
          language: ev.language,
          content: "",
          version: 0,
          streaming: true,
        },
      });
      return { ...state, openArtifactId: ev.id };
    }

    case "artifact_delta":
      return mutateArtifact(state, ev.id, (d) => ({ ...d, content: d.content + ev.text }));

    case "artifact_close":
      return mutateArtifact(state, ev.id, (d) => ({ ...d, streaming: false, version: ev.version }));

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
