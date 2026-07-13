// React binding over the turn-session store: subscribes the view to the ACTIVE
// conversation's session and exposes the user actions on it. All streaming state
// lives in turnSessions.ts (module-level, keyed by conversation), so switching
// conversations never aborts an in-flight turn — the detached session keeps
// streaming in the background and the view simply re-subscribes on return.

import { useCallback, useSyncExternalStore } from "react";

import type { AgentTurnRequest } from "../api/client";
import * as store from "./turnSessions";

export interface TurnConfig {
  model: string;
  provider?: string | null;
  effort?: string;
  permissionMode?: string | null;
  projectId?: string | null;
  options?: Record<string, boolean>;
  enabledMcp?: string[];
  enabledPlugins?: string[];
  // Response style (P0-6): normal | concise | explanatory | formal.
  style?: string;
}

function baseRequest(config: TurnConfig): Omit<AgentTurnRequest, "goal" | "history"> {
  return {
    model: config.model,
    provider: config.provider ?? null,
    effort: config.effort ?? "High",
    permission_mode: config.permissionMode ?? null,
    project_id: config.projectId ?? null,
    options: config.options ?? {},
    enabled_mcp: config.enabledMcp ?? [],
    enabled_plugins: config.enabledPlugins ?? [],
    // "normal" adds nothing server-side; omit it to keep requests clean.
    ...(config.style && config.style !== "normal" ? { style: config.style } : {}),
  };
}

export function useTranscript(config: TurnConfig) {
  const snap = useSyncExternalStore(store.subscribe, store.getSnapshot);

  const send = useCallback(
    (goal: string, images?: string[]) => store.sendActive(goal, baseRequest(config), images),
    [config],
  );
  // Regenerate the last answer. An optional override swaps the model/provider for just
  // this run (used by "regenerate with a different model") — everything else about the
  // turn (options, project, style) is unchanged.
  const retryLast = useCallback(
    (override?: { model: string; provider?: string | null }) =>
      store.retryActive(
        override
          ? { ...baseRequest(config), model: override.model, provider: override.provider ?? null }
          : baseRequest(config),
      ),
    [config],
  );
  const editAndResend = useCallback(
    (index: number, text: string) => store.editActive(index, text, baseRequest(config)),
    [config],
  );
  const stop = useCallback(() => store.stopActive(), []);
  const resolveApproval = useCallback(
    (decision: "approve" | "decline") => store.resolveApprovalActive(decision),
    [],
  );
  const markQuestionAnswered = useCallback((id: string) => store.markQuestionAnsweredActive(id), []);
  const openArtifact = useCallback((id: string) => store.setArtifactPanelActive(id), []);
  const closeArtifact = useCallback(() => store.setArtifactPanelActive(null), []);

  return {
    state: snap.state,
    busy: snap.busy,
    send,
    retryLast,
    editAndResend,
    stop,
    resolveApproval,
    markQuestionAnswered,
    openArtifact,
    closeArtifact,
  };
}
