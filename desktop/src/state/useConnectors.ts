// MCP connector management: the server list, add (stdio or remote), remove, and the
// set of servers enabled for the current session (fed into each turn as enabled_mcp).

import { useCallback, useEffect, useState } from "react";

import { type AddMcpBody, type McpServer, type McpbManifestInfo, mcp, type UserConfigField } from "../api/client";

// Pure toggle of an id in a string array (kept pure for testing).
export function toggleId(ids: string[], id: string): string[] {
  return ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id];
}

const ENABLED_KEY = "ocd.enabledConnectors";

function loadEnabled(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(ENABLED_KEY) ?? "[]");
    return Array.isArray(v) ? v.filter((x) => typeof x === "string") : [];
  } catch {
    return [];
  }
}

function saveEnabled(ids: string[]): void {
  try {
    localStorage.setItem(ENABLED_KEY, JSON.stringify(ids));
  } catch {
    /* storage unavailable */
  }
}

// Keep only enabled ids whose server is present AND not erroring — so a connector
// that has since failed (auth expired, process gone) is dropped from the set fed to
// the model instead of lingering and being reached for on every turn. Pure for tests.
export function reconcileEnabled(enabled: string[], servers: { id: string; status: string }[]): string[] {
  const healthy = new Set(servers.filter((s) => s.status !== "error").map((s) => s.id));
  return enabled.filter((id) => healthy.has(id));
}

// The user_config fields an extension REQUIRES the user to supply before it can
// launch. Fields with a default are pre-filled by the backend, so only
// required-and-defaultless ones need prompting. Kept pure for testing.
export function requiredFields(
  userConfig: Record<string, UserConfigField> | undefined,
): { key: string; field: UserConfigField }[] {
  return Object.entries(userConfig ?? {})
    .filter(([, f]) => f.required && f.default === undefined)
    .map(([key, field]) => ({ key, field }));
}

export function useConnectors() {
  const [servers, setServers] = useState<McpServer[]>([]);
  // Enabled set persists across sessions (a user's on/off choice sticks), and is
  // reconciled against the live server list so an erroring connector drops out.
  const [enabled, setEnabled] = useState<string[]>(loadEnabled);
  const [err, setErr] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await mcp.list();
      setServers(list);
      setEnabled((ids) => reconcileEnabled(ids, list));
    } catch (e) {
      setErr(String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Mirror every change to the enabled set into localStorage.
  useEffect(() => {
    saveEnabled(enabled);
  }, [enabled]);

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

  // One-click install of a .mcpb/.dxt extension bundle. Inspects the manifest,
  // prompts for any required user_config (API keys, paths…), installs, and enables
  // the server if it connected.
  const install = useCallback(
    async (file: File): Promise<McpServer | null> => {
      setErr(null);
      try {
        const info: McpbManifestInfo = await mcp.inspect(file);
        const values: Record<string, string> = {};
        for (const { key, field } of requiredFields(info.user_config)) {
          const label = field.title || key;
          const suffix = field.description ? ` — ${field.description}` : "";
          const v = window.prompt(`${info.name}: ${label}${suffix}`);
          if (v === null) return null; // user cancelled the install
          values[key] = v;
        }
        const s = await mcp.install(file, values);
        await refresh();
        if (s.status === "connected") setEnabled((ids) => (ids.includes(s.id) ? ids : [...ids, s.id]));
        else setErr(`${s.name}: ${s.detail || "failed to connect"}`);
        return s;
      } catch (e) {
        setErr(String(e));
        return null;
      }
    },
    [refresh],
  );

  const addOAuth = useCallback(
    async (name: string, url: string) => {
      setErr(null);
      try {
        await mcp.addOAuth(name, url);
        await refresh();
      } catch (e) {
        setErr(String(e));
      }
    },
    [refresh],
  );

  // Run the interactive OAuth authorize (opens the browser); enable on success.
  const authorize = useCallback(
    async (sid: string) => {
      setErr(null);
      try {
        const s = await mcp.authorize(sid);
        await refresh();
        if (s.status === "connected") setEnabled((ids) => (ids.includes(s.id) ? ids : [...ids, s.id]));
        else if (s.detail) setErr(`${s.name}: ${s.detail}`);
      } catch (e) {
        setErr(String(e));
      }
    },
    [refresh],
  );

  const toggle = useCallback((sid: string) => setEnabled((ids) => toggleId(ids, sid)), []);

  return { servers, enabled, err, add, addDemo, addOAuth, authorize, remove, toggle, install, refresh };
}
