// Scheduled ("automation") Cowork tasks: list/add/remove/toggle. Loaded when the Cowork
// tab is active. The backend ticker launches due schedules as background Cowork tasks.

import { useCallback, useEffect, useState } from "react";

import { type AddScheduleBody, type Schedule, schedules as api } from "../api/client";

export interface ScheduleDefaults {
  model: string;
  provider?: string | null;
  effort?: string;
  projectId?: string | null;
}

export function useSchedules(defaults: ScheduleDefaults, active: boolean) {
  const [items, setItems] = useState<Schedule[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setItems(await api.list());
      setErr(null);
    } catch (e) {
      setErr(String(e));
    }
  }, []);

  useEffect(() => {
    if (active) void refresh();
  }, [active, refresh]);

  const add = useCallback(
    async (body: Pick<AddScheduleBody, "goal" | "kind" | "every_seconds" | "at">) => {
      setErr(null);
      try {
        await api.add({
          ...body,
          model: defaults.model,
          provider: defaults.provider ?? null,
          effort: defaults.effort ?? "High",
          project_id: defaults.projectId ?? null,
        });
        await refresh();
      } catch (e) {
        setErr(String(e));
      }
    },
    [defaults, refresh],
  );

  const remove = useCallback(
    async (id: string) => {
      try {
        await api.remove(id);
        await refresh();
      } catch (e) {
        setErr(String(e));
      }
    },
    [refresh],
  );

  const toggle = useCallback(
    async (id: string, enabled: boolean) => {
      try {
        await api.setEnabled(id, enabled);
        await refresh();
      } catch (e) {
        setErr(String(e));
      }
    },
    [refresh],
  );

  return { items, err, refresh, add, remove, toggle };
}
