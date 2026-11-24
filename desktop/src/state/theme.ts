// Pure theme resolution. The user's preference is
// "system" | "light" | "dark" | "glass" | "glass-dark";
// "system" resolves against the OS's prefers-color-scheme.

export type ThemePref = "system" | "light" | "dark" | "glass" | "glass-dark";
export type ResolvedTheme = "light" | "dark" | "glass" | "glass-dark";

export function resolveTheme(pref: ThemePref, systemDark: boolean): ResolvedTheme {
  if (pref === "light" || pref === "dark" || pref === "glass" || pref === "glass-dark") return pref;
  return systemDark ? "dark" : "light";
}

// Cycle order for the toggle button: system -> light -> dark -> glass -> glass-dark -> system.
export function nextTheme(pref: ThemePref): ThemePref {
  if (pref === "system") return "light";
  if (pref === "light") return "dark";
  if (pref === "dark") return "glass";
  if (pref === "glass") return "glass-dark";
  return "system";
}

// Icon name + label for the toggle, reflecting the *preference* (not the resolved
// value) so the user can tell they're on "system" or one of the Liquid Glass modes.
export function themeGlyph(pref: ThemePref): {
  icon: "sun" | "moon" | "half" | "glass" | "glass-dark";
  label: string;
} {
  if (pref === "light") return { icon: "sun", label: "Light" };
  if (pref === "dark") return { icon: "moon", label: "Dark" };
  if (pref === "glass") return { icon: "glass", label: "Liquid Glass" };
  if (pref === "glass-dark") return { icon: "glass-dark", label: "Liquid Glass Dark" };
  return { icon: "half", label: "System" };
}

export function isThemePref(v: unknown): v is ThemePref {
  return v === "system" || v === "light" || v === "dark" || v === "glass" || v === "glass-dark";
}
