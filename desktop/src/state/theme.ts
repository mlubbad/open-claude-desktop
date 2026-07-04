// Pure theme resolution. The user's preference is "system" | "light" | "dark";
// "system" resolves against the OS's prefers-color-scheme.

export type ThemePref = "system" | "light" | "dark";
export type ResolvedTheme = "light" | "dark";

export function resolveTheme(pref: ThemePref, systemDark: boolean): ResolvedTheme {
  if (pref === "light" || pref === "dark") return pref;
  return systemDark ? "dark" : "light";
}

// Cycle order for the toggle button: system → light → dark → system.
export function nextTheme(pref: ThemePref): ThemePref {
  return pref === "system" ? "light" : pref === "light" ? "dark" : "system";
}

// A short glyph + label for the toggle, reflecting the *preference* (not the resolved
// value) so the user can tell they're on "system".
export function themeGlyph(pref: ThemePref): { icon: string; label: string } {
  if (pref === "light") return { icon: "☀", label: "Light" };
  if (pref === "dark") return { icon: "☾", label: "Dark" };
  return { icon: "◐", label: "System" };
}

export function isThemePref(v: unknown): v is ThemePref {
  return v === "system" || v === "light" || v === "dark";
}
