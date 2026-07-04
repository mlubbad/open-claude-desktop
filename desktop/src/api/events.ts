// The backend's SSE event vocabulary (frozen wire contract, mirrored from
// ocd_core/agent.py). The client renders these 1:1; do not diverge from the backend.

export type Scope = "answer" | "think";

export type AgentEvent =
  | { type: "turn_start"; turn_id: string }
  | { type: "think_open"; phase: string }
  | { type: "think_close"; elapsed: number }
  | { type: "answer_open" }
  | { type: "answer_to_think"; phase: string; elapsed: number }
  | { type: "delta"; scope: Scope; text: string }
  | {
      type: "tool";
      id: string;
      name: string;
      input: string;
      label_running: string;
      label_done: string;
      icon: string;
    }
  | { type: "tool_result"; id: string; name: string; summary: string }
  | { type: "tool_error"; id: string; name: string; text: string }
  | {
      type: "table";
      id: string;
      columns: string[];
      rows: Record<string, unknown>[];
      total: number;
      bytes: number;
    }
  | { type: "sources"; id: string; items: Source[] }
  // kind/title may be "" on a live-streamed update (the client keeps the existing values).
  | { type: "artifact_open"; id: string; title: string; kind: ArtifactKind | ""; language: string }
  | { type: "artifact_delta"; id: string; text: string }
  | { type: "artifact_close"; id: string; version: number }
  | { type: "approval_required"; turn_id: string; id: string; name: string; input: string }
  | {
      type: "usage";
      model: string;
      context_tokens: number;
      output_tokens: number;
      context_limit: number;
      context_pct: number;
      cost_usd: number | null;
    }
  | { type: "error"; text: string }
  | { type: "done" };

export interface Usage {
  model: string;
  context_tokens: number;
  output_tokens: number;
  context_limit: number;
  context_pct: number;
  cost_usd: number | null;
}

export interface Source {
  title?: string;
  url?: string;
  snippet?: string;
  domain?: string;
  favicon?: string;
}

export type ArtifactKind = "html" | "react" | "svg" | "mermaid" | "code" | "markdown";
