// MCP connector management: the server list, add (stdio or remote), remove, and the
// set of servers enabled for the current session (fed into each turn as enabled_mcp).

import { useCallback, useEffect, useState } from "react";

import { type AddMcpBody, type McpServer, mcp } from "../api/client";

// Pure toggle of an id in a string array (kept pure for testing).
export function toggleId(ids: string[], id: string): string[] {
  return ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id];
}

export function useConnectors() {
  const [servers, setServers] = useState<McpServer[]>([]);
  const [enabled, setEnabled] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setServers(await mcp.list());
    } catch (e) {
      setErr(String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const add = useCallback(
    async (body: AddMcpBody) => {
      setErr(null);
      try {
        const s = await mcp.add(body);
        await refresh();
        if (s.status === "connected") setEnabled((ids) => (ids.includes(s.id) ? ids : [...ids, s.id]));
        return s;
      } catch (e) {
        setErr(String(e));
        return null;
      }
    },
    [refresh],
  );

  const addDemo = useCallback(async () => {
    try {
      await mcp.addDemo();
      await refresh();
    } catch (e) {
      setErr(String(e));
    }
  }, [refresh]);

  const remove = useCallback(
    async (sid: string) => {
      try {
        await mcp.remove(sid);
      } catch (e) {
        setErr(String(e));
      }
      setEnabled((ids) => ids.filter((x) => x !== sid));
      await refresh();
    },
    [refresh],
  );

  const toggle = useCallback((sid: string) => setEnabled((ids) => toggleId(ids, sid)), []);

  return { servers, enabled, err, add, addDemo, remove, toggle, refresh };
}
