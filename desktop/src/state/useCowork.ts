// Cowork state: the background task list (polled while any task is running), the open
// task's detail, and start/cancel actions.

import { useCallback, useEffect, useRef, useState } from "react";

import { cowork as coworkApi, type CoworkDetail, type CoworkTask, replyPermission } from "../api/client";
import { hasRunning } from "./coworkView";

export interface CoworkConfig {
  model: string;
  provider?: string | null;
  effort?: string;
  projectId?: string | null;
}

export function useCowork(config: CoworkConfig, active: boolean) {
  const [tasks, setTasks] = useState<CoworkTask[]>([]);
  const [selected, setSelected] = useState<CoworkDetail | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const selectedId = useRef<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await coworkApi.list();
      setTasks(list);
      if (selectedId.current) {
        setSelected(await coworkApi.get(selectedId.current));
      }
      setErr(null);
    } catch (e) {
      setErr(String(e));
    }
  }, []);

  useEffect(() => {
    if (active) void refresh();
  }, [active, refresh]);

  // Poll while the tab is open and any task is still running.
  useEffect(() => {
    if (!active) return;
    const running = hasRunning(tasks) || (selected?.status === "running");
    if (!running) return;
    const t = setInterval(() => void refresh(), 2000);
    return () => clearInterval(t);
  }, [active, tasks, selected, refresh]);

  const start = useCallback(
    async (goal: string, approval: "skip" | "manual" = "skip") => {
      if (!goal.trim()) return;
      setErr(null);
      try {
        const t = await coworkApi.start({
          goal,
          model: config.model,
          provider: config.provider ?? null,
          effort: config.effort ?? "High",
          project_id: config.projectId ?? null,
          approval,
        });
        selectedId.current = t.id;
        await refresh();
      } catch (e) {
        setErr(String(e));
      }
    },
    [config, refresh],
  );

  // Drop all finished tasks ("Clear active").
  const clear = useCallback(async () => {
    try {
      await coworkApi.clear();
      await refresh();
    } catch (e) {
      setErr(String(e));
    }
  }, [refresh]);

  // Resolve a Manual-mode task's pending approval prompt (it runs with a turn_id, so
  // the shared permission endpoint applies) and immediately refresh so the task resumes.
  const resolveApproval = useCallback(
    async (turnId: string, toolCallId: string, decision: "approve" | "decline") => {
      try {
        await replyPermission(turnId, toolCallId, decision);
        await refresh();
      } catch (e) {
        setErr(String(e));
      }
    },
    [refresh],
  );

  const open = useCallback(async (id: string) => {
    selectedId.current = id;
    try {
      setSelected(await coworkApi.get(id));
    } catch (e) {
      setErr(String(e));
    }
  }, []);

  // Leave the task Review view (back to the Cowork home).
  const close = useCallback(() => {
    selectedId.current = null;
    setSelected(null);
  }, []);

  const cancel = useCallback(
    async (id: string) => {
      try {
        await coworkApi.cancel(id);
        await refresh();
      } catch (e) {
        setErr(String(e));
      }
    },
    [refresh],
  );

  return { tasks, selected, err, refresh, start, open, close, cancel, clear, resolveApproval };
}
