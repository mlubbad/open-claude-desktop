// Desktop-shell preferences (P1-9): the OS-global summon hotkey and close-to-tray.
// localStorage holds the user's intent; the live shell state is applied through
// platform.ts on startup and whenever a pref changes. Launch-at-login is NOT here —
// the OS autostart entry itself is the source of truth (see platform.isLaunchAtLogin).

export interface DesktopPrefs {
  summonHotkey: boolean; // OS-global Ctrl/Cmd+Shift+Space opens a new chat
  closeToTray: boolean; // closing the window hides to the tray instead of quitting
}

export const DEFAULT_DESKTOP_PREFS: DesktopPrefs = { summonHotkey: true, closeToTray: true };

const KEY = "ocd.desktopPrefs";
// Same-window change signal: App applies the hotkey/tray behavior, Settings renders
// the switches — different components, one source of truth.
export const DESKTOP_PREFS_EVENT = "ocd:desktop-prefs";

// Pure for tests: tolerate missing/corrupt storage and unknown fields.
export function parseDesktopPrefs(raw: string | null): DesktopPrefs {
  try {
    const v: unknown = JSON.parse(raw ?? "");
    if (v && typeof v === "object") {
      const o = v as Record<string, unknown>;
      return {
        summonHotkey: typeof o.summonHotkey === "boolean" ? o.summonHotkey : DEFAULT_DESKTOP_PREFS.summonHotkey,
        closeToTray: typeof o.closeToTray === "boolean" ? o.closeToTray : DEFAULT_DESKTOP_PREFS.closeToTray,
      };
    }
  } catch {
    /* fall through */
  }
  return { ...DEFAULT_DESKTOP_PREFS };
}

export function loadDesktopPrefs(): DesktopPrefs {
  try {
    return parseDesktopPrefs(localStorage.getItem(KEY));
  } catch {
    return { ...DEFAULT_DESKTOP_PREFS };
  }
}

export function saveDesktopPrefs(p: DesktopPrefs): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(p));
  } catch {
    /* storage unavailable */
  }
  try {
    window.dispatchEvent(new CustomEvent<DesktopPrefs>(DESKTOP_PREFS_EVENT, { detail: p }));
  } catch {
    /* no window (tests) */
  }
}

// Subscribe to pref changes made elsewhere in this window. Returns an unlisten fn.
export function onDesktopPrefsChange(handler: (p: DesktopPrefs) => void): () => void {
  if (typeof window === "undefined") return () => {};
  const fn = (e: Event) => handler((e as CustomEvent<DesktopPrefs>).detail);
  window.addEventListener(DESKTOP_PREFS_EVENT, fn);
  return () => window.removeEventListener(DESKTOP_PREFS_EVENT, fn);
}
