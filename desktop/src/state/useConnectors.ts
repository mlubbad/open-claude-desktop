// MCP connector management: the server list, add (stdio or remote), remove, and the
// set of servers enabled for the current session (fed into each turn as enabled_mcp).

import { useCallback, useEffect, useMemo, useState } from "react";

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
// This derives the runtime "active" set; it must NOT be written back to the persisted
// intent, or a momentary error would forget the user's choice for good (see below).
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
  // `enabled` is the user's PERSISTED intent (their on/off choice). It is only ever
  // mutated by explicit actions (toggle/add/remove/authorize/install) — never by a
  // refresh. Previously refresh() reconciled it against health and persisted the
  // result, so a momentary status:"error" (auth blip, process restart) permanently
  // un-toggled the connector: on recovery it stayed off until re-toggled by hand.
  const [enabled, setEnabled] = useState<string[]>(loadEnabled);
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

  // Mirror the user's intent (only) into localStorage.
  useEffect(() => {
    saveEnabled(enabled);
  }, [enabled]);

  // The runtime set fed to each turn: intent ∩ healthy servers. Derived, never
  // persisted — so when an erroring connector recovers it re-enters automatically.
  const active = useMemo(() => reconcileEnabled(enabled, servers), [enabled, servers]);

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

  // Enable/disable ONE tool within a connector (P1-12); persisted server-side.
  const setToolEnabled = useCallback(
    async (sid: string, tool: string, on: boolean) => {
      try {
        const updated = await mcp.setToolEnabled(sid, tool, on);
        setServers((list) => list.map((s) => (s.id === sid ? updated : s)));
      } catch (e) {
        setErr(String(e));
      }
    },
    [],
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

  // Re-connect an errored server from scratch (the error card's Retry). Recovers a
  // first-run download timeout or a since-fixed PATH without removing and re-adding.
  // Discovery can legitimately take a while on a cold start, so track which server
  // is retrying for the button label.
  const [retrying, setRetrying] = useState<string | null>(null);
  const retry = useCallback(
    async (sid: string) => {
      setErr(null);
      setRetrying(sid);
      try {
        const s = await mcp.refresh(sid);
        await refresh();
        if (s.status === "connected") setEnabled((ids) => (ids.includes(s.id) ? ids : [...ids, s.id]));
      } catch (e) {
        setErr(String(e));
      } finally {
        setRetrying(null);
      }
    },
    [refresh],
  );

  const toggle = useCallback((sid: string) => setEnabled((ids) => toggleId(ids, sid)), []);

  // `enabled` = the user's intent (drives the checkboxes); `active` = intent ∩ healthy
  // (fed to turns as enabled_mcp). Keeping them distinct is the whole point of F4.
  return { servers, enabled, active, err, add, addOAuth, authorize, remove, toggle, install, refresh, retry, retrying, setToolEnabled };
}
