// Curated, model-agnostic starter prompts shown on a fresh chat's empty state.
// Each chip's `prompt` is what gets sent; `label` is the short display text.

export interface Starter {
  icon: "pen" | "book" | "bug" | "chart" | "note" | "bulb";
  label: string;
  prompt: string;
  wide?: boolean; // the centered "choice" chip on its own row
}

// The empty-state chip row, mirroring the reference's Write · Learn · Code · Life
// stuff + a centered "choice" chip (contract §0.3). Each chip opens an intent, then
// the model asks what's needed — model-agnostic, no domain assumptions.
export const STARTER_GROUPS: Starter[] = [
  { icon: "pen", label: "Write", prompt: "Help me write something. Ask me what it's for and the key points, then draft it." },
  { icon: "book", label: "Learn", prompt: "Teach me about a topic I choose — clear explanation, an analogy, and a small example." },
  { icon: "bug", label: "Code", prompt: "Help me with code. Ask for the language, the goal, and any error, then work through it." },
  { icon: "bulb", label: "Life stuff", prompt: "Help me think through something in my life. Ask a couple of questions first." },
  { icon: "note", label: "Surprise me", prompt: "Pick something genuinely useful or interesting to help me with and get started.", wide: true },
];

// Back-compat alias (kept for existing imports/tests).
export const STARTER_PROMPTS = STARTER_GROUPS;
