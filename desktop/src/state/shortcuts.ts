// The app's keyboard shortcuts, as a pure registry for the help modal. `keys` uses ⌘
// on mac and shows the same glyphs everywhere (Ctrl maps to ⌘ visually for brevity).

export interface Shortcut {
  keys: string;
  action: string;
}

export const SHORTCUTS: Shortcut[] = [
  { keys: "⌘K", action: "Open the command palette / search chats" },
  { keys: "⌘⇧O", action: "Start a new chat" },
  { keys: "Enter", action: "Send the message" },
  { keys: "⇧Enter", action: "New line in the message" },
  { keys: "/", action: "Show skills (at the start of a message)" },
  { keys: "Esc", action: "Stop generating / close a panel" },
  { keys: "?", action: "Show this shortcuts list" },
];

// Whether a keyboard event originated from an editable field, where printable-character
// shortcuts (like "?") must NOT fire.
export function isEditableTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null;
  if (!el || !el.tagName) return false;
  const tag = el.tagName.toLowerCase();
  return tag === "input" || tag === "textarea" || el.isContentEditable === true;
}
