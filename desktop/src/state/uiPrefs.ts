// Local UI preferences that need no backend: chat font and motion. Persisted in
// localStorage and applied as data-attributes on <html>, which styles.css picks up
// (data-chat-font="serif|sans", data-motion="system|reduced").

export type ChatFont = "serif" | "sans";
export type MotionPref = "system" | "reduced";

const FONT_KEY = "ocd.chatFont";
const MOTION_KEY = "ocd.motion";

export function getChatFont(): ChatFont {
  try {
    return localStorage.getItem(FONT_KEY) === "sans" ? "sans" : "serif";
  } catch {
    return "serif";
  }
}

export function getMotion(): MotionPref {
  try {
    return localStorage.getItem(MOTION_KEY) === "reduced" ? "reduced" : "system";
  } catch {
    return "system";
  }
}

export function setChatFont(f: ChatFont): void {
  try {
    localStorage.setItem(FONT_KEY, f);
  } catch {
    /* storage unavailable */
  }
  applyUiPrefs();
}

export function setMotion(m: MotionPref): void {
  try {
    localStorage.setItem(MOTION_KEY, m);
  } catch {
    /* storage unavailable */
  }
  applyUiPrefs();
}

// Stamp the current preferences onto <html>; call once at startup and after changes.
export function applyUiPrefs(): void {
  if (typeof document === "undefined") return;
  document.documentElement.dataset.chatFont = getChatFont();
  document.documentElement.dataset.motion = getMotion();
}
