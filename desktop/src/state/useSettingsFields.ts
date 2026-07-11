// One mount-fetch + patch-save for a Settings page/section. Every live settings page
// used to hand-roll the same get().then(...) boilerplate — and worse, re-submit ALL
// of its fields on each save from possibly-stale closures. This hook retires both:
// `save(patch)` persists ONLY the patch (the backend merges), and `set(patch)`
// buffers text inputs locally until their onBlur save.

import { useCallback, useEffect, useState } from "react";

import { type AppSettings, settings as settingsApi } from "../api/client";

export function useSettingsFields() {
  const [values, setValues] = useState<AppSettings | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    settingsApi
      .get()
      .then(setValues)
      .catch((e) => setErr(String(e)));
  }, []);

  // Buffer a change locally (text inputs while typing).
  const set = useCallback((patch: Partial<AppSettings>) => {
    setValues((v) => (v ? { ...v, ...patch } : v));
  }, []);

  // Persist a patch — and only the patch — mirroring it locally.
  const save = useCallback((patch: Partial<AppSettings>) => {
    setValues((v) => (v ? { ...v, ...patch } : v));
    void settingsApi.save(patch).catch((e) => setErr(String(e)));
  }, []);

  return { values, set, save, err };
}
