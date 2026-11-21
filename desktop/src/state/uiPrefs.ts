// Local UI preferences that need no backend: chat font and motion. Persisted in
// localStorage and applied to <html> at startup and after every change. Motion is a
// data-attribute (data-motion="system|reduced") that styles.css keys off; the chat
// font drives the `--font-serif` custom property directly (inline style on <html>),
// so picking a font re-flows every surface that reads var(--font-serif) — the whole app.

export type MotionPref = "system" | "reduced";

// A selectable font. `stack` is the CSS font-family value applied to `--font-serif`;
// `null` means "use the default stack from :root" (the editorial serif chain), so the
// default option clears the override rather than duplicating that long stack here.
export interface FontOption {
  value: string;
  label: string;
  stack: string | null;
}

// The fonts offered in Settings → Chat font. Every entry is a concrete, resolvable
// family. The DEFAULT is "Newsreader" — the bundled SIL OFL editorial typeface
// (see styles.css @font-face) — applied via the :root --font-serif stack (stack: null),
// which is why it needs no explicit stack here. The rest are alternatives: the bundled
// open Noto Serif, two classic serifs, the system sans, and a monospace.
export const FONT_OPTIONS: FontOption[] = [
  { value: "serif", label: "Newsreader (Editorial)", stack: null },
  { value: "noto", label: "Noto Serif", stack: '"Noto Serif", Georgia, serif' },
  { value: "georgia", label: "Georgia", stack: 'Georgia, "Times New Roman", Times, serif' },
  { value: "times", label: "Times New Roman", stack: '"Times New Roman", Times, serif' },
  { value: "system", label: "System Sans", stack: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif' },
  { value: "mono", label: "Monospace", stack: 'ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace' },
];

export type ChatFont = (typeof FONT_OPTIONS)[number]["value"];

const DEFAULT_FONT: ChatFont = "serif";

const FONT_KEY = "ocd.chatFont";
const MOTION_KEY = "ocd.motion";

function fontOption(value: string): FontOption | undefined {
  return FONT_OPTIONS.find((o) => o.value === value);
}

export function getChatFont(): ChatFont {
  try {
    const v = localStorage.getItem(FONT_KEY);
    // "sans" is the legacy key for the system-sans option; keep it working.
    if (v === "sans") return "system";
    return v && fontOption(v) ? v : DEFAULT_FONT;
  } catch {
    return DEFAULT_FONT;
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
  const root = document.documentElement;
  const font = getChatFont();
  root.dataset.chatFont = font;
  const stack = fontOption(font)?.stack ?? null;
  // Inline `--font-serif` wins over the :root stack; clearing it restores the default.
  if (stack) root.style.setProperty("--font-serif", stack);
  else root.style.removeProperty("--font-serif");
  root.dataset.motion = getMotion();
}
