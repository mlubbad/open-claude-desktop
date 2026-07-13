import { useEffect, useState } from "react";

import { checkBackendHealth, isTauriShell } from "../api/client";

// Poll the backend sidecar's liveness (desktop shell only — on the web the backend isn't
// ours to watch). Starts optimistic and only reports "down" after two consecutive failed
// probes, so a single dropped request during the shell's auto-restart doesn't flash the
// banner; recovers on the first success. Returns true (healthy) when not in the shell.
export function useBackendHealth(intervalMs = 5000): boolean {
  const [ok, setOk] = useState(true);
  useEffect(() => {
    if (!isTauriShell()) return; // web: backend runs separately, nothing to watch
    let alive = true;
    let misses = 0;
    const tick = async () => {
      const healthy = await checkBackendHealth();
      if (!alive) return;
      misses = healthy ? 0 : misses + 1;
      setOk(healthy || misses < 2);
    };
    void tick();
    const id = window.setInterval(tick, intervalMs);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, [intervalMs]);
  return ok;
}
