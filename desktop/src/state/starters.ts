// Curated, model-agnostic starter prompts shown on a fresh chat's empty state.
// Each chip's `prompt` is what gets sent; `label` is the short display text.

export interface Starter {
  icon: "pen" | "book" | "bug" | "chart" | "note" | "bulb";
  label: string;
  prompt: string;
}

export const STARTER_PROMPTS: Starter[] = [
  {
    icon: "pen",
    label: "Draft an email",
    prompt: "Help me draft a concise, friendly email. First ask me who it's for and the goal.",
  },
  {
    icon: "book",
    label: "Explain a concept",
    prompt: "Explain a concept I choose in simple terms with an analogy and a small example.",
  },
  {
    icon: "bug",
    label: "Debug some code",
    prompt: "I have a bug. Ask me for the code and the error, then help me find and fix the cause.",
  },
  {
    icon: "chart",
    label: "Make a chart",
    prompt: "Create a small self-contained HTML bar chart from data I provide, as an artifact.",
  },
  {
    icon: "note",
    label: "Summarize text",
    prompt: "Summarize a document or article I paste into the key points and any action items.",
  },
  {
    icon: "bulb",
    label: "Brainstorm ideas",
    prompt: "Brainstorm a diverse list of ideas for a topic I give you, grouped by theme.",
  },
];
