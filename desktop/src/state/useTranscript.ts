// React binding around the pure transcript reducer: manages the live turn, the SSE
// stream, and HITL approvals. Keeps all streaming semantics in transcript.ts.

import { useCallback, useReducer, useRef, useState } from "react";

import { type AgentTurnRequest, replyPermission, streamTurn } from "../api/client";
import type { AgentEvent } from "../api/events";
import {
  applyEvent,
  buildHistory,
  initialState,
  lastUserIndex,
  loadMessages,
  type Message,
  retryFrom,
  startTurn,
  type TranscriptState,
  type UserMessage,
} from "./transcript";

type Action =
  | { kind: "event"; ev: AgentEvent }
  | { kind: "start"; goal: string }
  | { kind: "retry"; userIdx: number }
  | { kind: "load"; messages: Message[] }
  | { kind: "panel"; artifactId: string | null }
  | { kind: "reset" };

function reducer(state: TranscriptState, action: Action): TranscriptState {
  switch (action.kind) {
    case "event":
      return applyEvent(state, action.ev);
    case "start":
      return startTurn(state, action.goal);
    case "retry":
      return retryFrom(state, action.userIdx);
    case "load":
      return loadMessages(action.messages);
    case "panel":
      return { ...state, openArtifactId: action.artifactId };
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

  const stop = useCallback(() => {
    ctrlRef.current?.abort();
    setBusy(false);
    dispatch({ kind: "event", ev: { type: "done" } });
  }, []);

  const resolveApproval = useCallback(
    async (decision: "approve" | "decline") => {
      const p = state.pendingApproval;
      if (!p) return;
      await replyPermission(p.turnId, p.toolCallId, decision);
    },
    [state.pendingApproval],
  );

  const reset = useCallback(() => dispatch({ kind: "reset" }), []);
  const load = useCallback((messages: Message[]) => dispatch({ kind: "load", messages }), []);
  const openArtifact = useCallback((id: string) => dispatch({ kind: "panel", artifactId: id }), []);
  const closeArtifact = useCallback(() => dispatch({ kind: "panel", artifactId: null }), []);

  return { state, busy, send, retryLast, stop, resolveApproval, reset, load, openArtifact, closeArtifact };
}
