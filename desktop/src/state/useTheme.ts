// Applies the theme preference: stamps data-theme on <html>, follows the OS while the
// preference is "system", and persists changes to app settings.

import { useCallback, useEffect, useState } from "react";

import { settings as settingsApi } from "../api/client";
import { isThemePref, nextTheme, resolveTheme, type ThemePref } from "./theme";

function systemPrefersDark(): boolean {
  return typeof window !== "undefined" && !!window.matchMedia?.("(prefers-color-scheme: dark)").matches;
}

function apply(pref: ThemePref): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.theme = resolveTheme(pref, systemPrefersDark());
}

export function useTheme() {
  const [pref, setPref] = useState<ThemePref>("system");

  // Load the saved preference once.
  useEffect(() => {
    settingsApi
      .get()
      .then((s) => {
        const p = isThemePref(s.theme) ? s.theme : "system";
        setPref(p);
      })
      .catch(() => {});
  }, []);

  // Re-apply whenever the preference changes, and track OS changes while on "system".
  useEffect(() => {
    apply(pref);
    if (pref !== "system" || typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => apply("system");
    mq.addEventListener?.("change", onChange);
    return () => mq.removeEventListener?.("change", onChange);
  }, [pref]);

  const set = useCallback((p: ThemePref) => {
    setPref(p);
    void settingsApi.save({ theme: p }).catch(() => {});
  }, []);

  const cycle = useCallback(() => set(nextTheme(pref)), [pref, set]);

  return { pref, set, cycle };
}
