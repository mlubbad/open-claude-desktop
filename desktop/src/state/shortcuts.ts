// The app's keyboard shortcuts, as a pure registry for the help modal. The modifier
// glyphs are platform-aware: ⌘/⇧ on macOS, Ctrl+/Shift+ elsewhere (the handlers
// already accept both metaKey and ctrlKey).

export interface Shortcut {
  keys: string;
  action: string;
}

export function shortcutsFor(isMac: boolean): Shortcut[] {
  const mod = isMac ? "⌘" : "Ctrl+";
  const shift = isMac ? "⇧" : "Shift+";
  return [
    { keys: `${mod}K`, action: "Open the command palette / search chats" },
    { keys: `${mod}${shift}O`, action: "Start a new chat" },
    { keys: "Enter", action: "Send the message" },
    { keys: `${shift}Enter`, action: "New line in the message" },
    { keys: "/", action: "Show skills (at the start of a message)" },
    { keys: "Esc", action: "Stop generating / close a panel" },
    { keys: "?", action: "Show this shortcuts list" },
  ];
}

export const IS_MAC =
  typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform ?? "");

export const SHORTCUTS: Shortcut[] = shortcutsFor(IS_MAC);

// Whether a keyboard event originated from an editable field, where printable-character
// shortcuts (like "?") must NOT fire.
export function isEditableTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || !el.tagName) return false;
  const tag = el.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || el.isContentEditable === true;
}
