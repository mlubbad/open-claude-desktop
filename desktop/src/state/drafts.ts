// Unsent composer text, keyed by conversation id (or "new" for a fresh chat). Pure +
// immutable so switching chats can save/restore a draft deterministically.

export type Drafts = Record<string, string>;

export function getDraft(drafts: Drafts, key: string): string {
  return drafts[key] ?? "";
}

// Store the draft for `key`, pruning the entry when it's blank so the map doesn't grow
// with empty strings.
export function setDraft(drafts: Drafts, key: string, text: string): Drafts {
  const next = { ...drafts };
  if (text.trim()) next[key] = text;
  else delete next[key];
  return next;
}
