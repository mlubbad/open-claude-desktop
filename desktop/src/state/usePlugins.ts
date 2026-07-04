// Plugin management: installed plugins (with the per-session enabled set fed into each
// turn as enabled_plugins), plus the bundled marketplace (browse / install / uninstall).

import { useCallback, useEffect, useState } from "react";

import { type MarketplacePlugin, plugins as pluginsApi, type PluginSummary } from "../api/client";
import { toggleId } from "./useConnectors";

export function usePlugins() {
  const [installed, setInstalled] = useState<PluginSummary[]>([]);
  const [market, setMarket] = useState<MarketplacePlugin[]>([]);
  const [enabled, setEnabled] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [inst, cat] = await Promise.all([pluginsApi.list(), pluginsApi.marketplace()]);
      setInstalled(inst);
      setMarket(cat);
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

  return { installed, market, enabled, err, busy, refresh, toggle, install, uninstall };
}
