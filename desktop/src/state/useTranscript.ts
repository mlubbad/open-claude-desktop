// React binding around the pure transcript reducer: manages the live turn, the SSE
// stream, and HITL approvals. Keeps all streaming semantics in transcript.ts.

import { useCallback, useReducer, useRef, useState } from "react";

import { type AgentTurnRequest, replyPermission, streamTurn } from "../api/client";
import type { AgentEvent } from "../api/events";
import { applyEvent, initialState, startTurn, type TranscriptState } from "./transcript";

type Action = { kind: "event"; ev: AgentEvent } | { kind: "start"; goal: string } | { kind: "reset" };

function reducer(state: TranscriptState, action: Action): TranscriptState {
  switch (action.kind) {
    case "event":
      return applyEvent(state, action.ev);
    case "start":
      return startTurn(state, action.goal);
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
}

export function useTranscript(config: TurnConfig) {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);
  const [busy, setBusy] = useState(false);
  const ctrlRef = useRef<AbortController | null>(null);

  const send = useCallback(
    (goal: string) => {
      if (busy || !goal.trim()) return;
      setBusy(true);
      dispatch({ kind: "start", goal });

      // Reconstruct chat history for the backend from prior finalized messages.
      const history = state.messages.map((m) =>
        m.role === "user"
          ? { role: "user", content: m.text, kind: "user" }
          : {
              role: "assistant",
              content: m.blocks
                .filter((b) => b.kind === "answer")
                .map((b) => (b.kind === "answer" ? b.text : ""))
                .join("\n"),
              kind: "final",
            },
      );

      const req: AgentTurnRequest = {
        goal,
        history,
        model: config.model,
        provider: config.provider ?? null,
        effort: config.effort ?? "High",
        permission_mode: config.permissionMode ?? null,
        project_id: config.projectId ?? null,
        options: config.options ?? {},
      };

      ctrlRef.current = streamTurn(
        req,
        (ev) => {
          dispatch({ kind: "event", ev });
          if (ev.type === "done" || ev.type === "error") setBusy(false);
        },
        () => setBusy(false),
      );
    },
    [busy, config, state.messages],
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
      await replyPermission(p.turnId, p.toolCallId, decision);
    },
    [state.pendingApproval],
  );

  const reset = useCallback(() => dispatch({ kind: "reset" }), []);

  return { state, busy, send, stop, resolveApproval, reset };
}
