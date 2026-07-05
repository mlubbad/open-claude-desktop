// React binding around the pure transcript reducer: manages the live turn, the SSE
// stream, and HITL approvals. Keeps all streaming semantics in transcript.ts.

import { useCallback, useReducer, useRef, useState } from "react";

import { type AgentTurnRequest, replyPermission, streamTurn } from "../api/client";
import type { AgentEvent } from "../api/events";
import {
  applyEvent,
  buildHistory,
  editFrom,
  initialState,
  lastUserIndex,
  loadMessages,
  type Message,
  resolveApprovalState,
  restoreApprovalState,
  retryFrom,
  startTurn,
  type TranscriptState,
  type UserMessage,
} from "./transcript";

type Action =
  | { kind: "event"; ev: AgentEvent }
  | { kind: "start"; goal: string }
  | { kind: "retry"; userIdx: number }
  | { kind: "edit"; index: number; text: string }
  | { kind: "load"; messages: Message[] }
  | { kind: "panel"; artifactId: string | null }
  | { kind: "approval"; decision: "approve" | "decline"; toolCallId: string }
  | { kind: "approval_restore"; pending: NonNullable<TranscriptState["pendingApproval"]> }
  | { kind: "reset" };

function reducer(state: TranscriptState, action: Action): TranscriptState {
  switch (action.kind) {
    case "event":
      return applyEvent(state, action.ev);
    case "start":
      return startTurn(state, action.goal);
    case "retry":
      return retryFrom(state, action.userIdx);
    case "edit":
      return editFrom(state, action.index, action.text);
    case "load":
      return loadMessages(action.messages);
    case "panel":
      return { ...state, openArtifactId: action.artifactId };
    case "approval":
      return resolveApprovalState(state, action.decision, action.toolCallId);
    case "approval_restore":
      return restoreApprovalState(state, action.pending);
    case "reset":
      return initialState();
  }
}

export interface TurnConfig {
  model: string;
  provider?: string | null;
  effort?: string;
  permissionMode?: string | null;
  projectId?: string | null;
  options?: Record<string, boolean>;
  enabledMcp?: string[];
  enabledPlugins?: string[];
}

export function useTranscript(config: TurnConfig) {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);
  const [busy, setBusy] = useState(false);
  const ctrlRef = useRef<AbortController | null>(null);

  // Launch a turn: `history` is the prior context (already excludes the new goal).
  const launch = useCallback(
    (goal: string, history: ReturnType<typeof buildHistory>) => {
      const req: AgentTurnRequest = {
        goal,
        history,
        model: config.model,
        provider: config.provider ?? null,
        effort: config.effort ?? "High",
        permission_mode: config.permissionMode ?? null,
        project_id: config.projectId ?? null,
        options: config.options ?? {},
        enabled_mcp: config.enabledMcp ?? [],
        enabled_plugins: config.enabledPlugins ?? [],
      };
      setBusy(true);
      ctrlRef.current = streamTurn(
        req,
        (ev) => {
          dispatch({ kind: "event", ev });
          if (ev.type === "done" || ev.type === "error") setBusy(false);
        },
        () => setBusy(false),
      );
    },
    [config],
  );

  const send = useCallback(
    (goal: string) => {
      if (busy || !goal.trim()) return;
      const history = buildHistory(state.messages);
      dispatch({ kind: "start", goal });
      launch(goal, history);
    },
    [busy, launch, state.messages],
  );

  // Regenerate the most recent assistant response for the last user message.
  const retryLast = useCallback(() => {
    if (busy) return;
    const idx = lastUserIndex(state.messages);
    if (idx < 0) return;
    const goal = (state.messages[idx] as UserMessage).text;
    const history = buildHistory(state.messages.slice(0, idx));
    dispatch({ kind: "retry", userIdx: idx });
    launch(goal, history);
  }, [busy, launch, state.messages]);

  // Edit a prior user message and re-run from there (drops later messages).
  const editAndResend = useCallback(
    (index: number, text: string) => {
      if (busy || !text.trim()) return;
      const history = buildHistory(state.messages.slice(0, index));
      dispatch({ kind: "edit", index, text });
      launch(text, history);
    },
    [busy, launch, state.messages],
  );

  const stop = useCallback(() => {
    ctrlRef.current?.abort();
    setBusy(false);
    dispatch({ kind: "event", ev: { type: "done" } });
  }, []);

  const resolveApproval = useCallback(
    async (decision: "approve" | "decline") => {
      const p = state.pendingApproval;
      if (!p) return;
      // Dismiss the prompt immediately — the user decided; the stream's follow-up
      // events (tool_result / tool_error) carry the backend's authoritative outcome.
      // The id pins the dispatch to THIS approval in case another one arrives first.
      dispatch({ kind: "approval", decision, toolCallId: p.toolCallId });
      try {
        await replyPermission(p.turnId, p.toolCallId, decision);
      } catch {
        // The decision never reached the backend (it would eventually time the tool
        // out as a decline). Re-arm the prompt so the user can decide again.
        dispatch({ kind: "approval_restore", pending: p });
      }
    },
    [state.pendingApproval],
  );

  // Loading another conversation or starting fresh must first sever the live SSE
  // stream — otherwise its remaining events would graft onto (and auto-save into)
  // whatever transcript replaced the streaming one.
  const abortStream = useCallback(() => {
    ctrlRef.current?.abort();
    ctrlRef.current = null;
    setBusy(false);
  }, []);

  const reset = useCallback(() => {
    abortStream();
    dispatch({ kind: "reset" });
  }, [abortStream]);
  const load = useCallback(
    (messages: Message[]) => {
      abortStream();
      dispatch({ kind: "load", messages });
    },
    [abortStream],
  );
  const openArtifact = useCallback((id: string) => dispatch({ kind: "panel", artifactId: id }), []);
  const closeArtifact = useCallback(() => dispatch({ kind: "panel", artifactId: null }), []);

  return { state, busy, send, retryLast, editAndResend, stop, resolveApproval, reset, load, openArtifact, closeArtifact };
}
