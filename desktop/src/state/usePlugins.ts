// Plugin management: installed plugins (with the per-session enabled set fed into each
// turn as enabled_plugins), plus the bundled marketplace (browse / install / uninstall).

import { useCallback, useEffect, useState } from "react";

import {
  type MarketplacePlugin,
  type MarketplaceSource,
  plugins as pluginsApi,
  type PluginSummary,
} from "../api/client";
import { toggleId } from "./useConnectors";

export function usePlugins() {
  const [installed, setInstalled] = useState<PluginSummary[]>([]);
  const [market, setMarket] = useState<MarketplacePlugin[]>([]);
  const [sources, setSources] = useState<MarketplaceSource[]>([]);
  const [allowRemote, setAllowRemote] = useState(false);
  const [enabled, setEnabled] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [inst, cat, src] = await Promise.all([
        pluginsApi.list(),
        pluginsApi.marketplace(),
        pluginsApi.sources().catch(() => ({ allow_remote: false, sources: [] })),
      ]);
      setInstalled(inst);
      setMarket(cat);
      setSources(src.sources);
      setAllowRemote(src.allow_remote);
      // Drop any enabled ids that are no longer installed.
      setEnabled((ids) => ids.filter((id) => inst.some((p) => p.name === id)));
      setErr(null);
    } catch (e) {
      setErr(String(e));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Sync a git repo as a marketplace source (runs its plugin code on install — the UI
  // warns first). Returns the error message on failure, or null on success.
  const addSource = useCallback(
    async (url: string, ref = "", name = ""): Promise<string | null> => {
      setBusy("__source__");
      setErr(null);
      try {
        await pluginsApi.addSource(url, ref, name);
        await refresh();
        return null;
      } catch (e) {
        return e instanceof Error ? e.message : String(e);
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  const removeSource = useCallback(
    async (id: string) => {
      setBusy(id);
      try {
        await pluginsApi.removeSource(id);
        await refresh();
      } catch (e) {
        setErr(String(e));
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  const toggle = useCallback((name: string) => setEnabled((ids) => toggleId(ids, name)), []);

  const install = useCallback(
    async (name: string) => {
      setBusy(name);
      setErr(null);
      try {
        await pluginsApi.install(name);
        await refresh();
      } catch (e) {
        setErr(String(e));
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  const uninstall = useCallback(
    async (name: string) => {
      setBusy(name);
      setErr(null);
      try {
        await pluginsApi.uninstall(name);
        setEnabled((ids) => ids.filter((x) => x !== name));
        await refresh();
      } catch (e) {
        setErr(String(e));
      } finally {
        setBusy(null);
      }
    },
    [refresh],
  );

  return {
    installed, market, sources, allowRemote, enabled, err, busy,
    refresh, toggle, install, uninstall, addSource, removeSource,
  };
}
