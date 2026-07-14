// UI copy for the model + effort picker. Descriptors are best-effort, keyed on the
// bare model name (any "provider/" prefix stripped) — purely cosmetic labels for the
// picker; the real capability lookup lives in the backend catalog.

export interface EffortLevel {
  value: string;
  tag?: string; // e.g. "Default"
  info?: boolean; // show a small info glyph
}

// The five extended-thinking levels, mirroring the reference picker. Each maps to
// real backend behaviour (steps/plan/verify/temp) in agent.EFFORT.
export const EFFORT_LEVELS: EffortLevel[] = [
  { value: "Low" },
  { value: "Medium" },
  { value: "High", tag: "Default" },
  { value: "Extra", info: true },
  { value: "Max", info: true },
];

const DESCRIPTORS: [RegExp, string][] = [
  [/gpt-4o-mini|mini|flash|turbo|haiku|instant|8b/i, "Fastest for quick answers."],
  [/glm-5|reasoner|o3|o1|thinking|glm-4\.5|deepseek-r/i, "For your toughest challenges."],
  [/gpt-4o|opus|glm-4\.6|glm-4-plus|qwen-max|70b|72b|deepseek-chat|deepseek-v3/i, "For complex tasks."],
  [/sonnet|plus|glm-4-air|glm-4-long|qwen-plus/i, "Most efficient for everyday tasks."],
];

// A provider's EFFECTIVE model list: the user's custom additions first (newest
// intent), then the built-in catalog, with the models the user removed filtered out
// and duplicates collapsed. This is the single source every surface derives from — the
// Settings card, the composer picker, and the retry menu — so a custom model name is
// offered everywhere and a removed one disappears everywhere. All args optional; with no
// customisation it returns the built-in catalog unchanged.
export function effectiveCatalog(
  base: string[],
  custom?: string[],
  hidden?: string[],
): string[] {
  const hide = new Set(hidden ?? []);
  const seen = new Set<string>();
  const out: string[] = [];
  for (const m of [...(custom ?? []), ...(base ?? [])]) {
    const name = (m ?? "").trim();
    if (!name || hide.has(name) || seen.has(name)) continue;
    seen.add(name);
    out.push(name);
  }
  return out;
}

// Without a user selection, the picker shows only the first few of a provider's
// catalog (catalogs are ordered newest-first) — the rest live in Settings.
export const DEFAULT_PICKER_COUNT = 6;

// The models a provider shows in the chat picker: the user's Settings selection when
// one exists, else the newest few — always including the currently-active model.
export function pickerModels(
  catalog: string[],
  chosen: string[] | undefined,
  current: string,
): string[] {
  const wanted = chosen?.length
    ? catalog.filter((m) => chosen.includes(m))
    : catalog.slice(0, DEFAULT_PICKER_COUNT);
  const out = wanted.length ? wanted : catalog.slice(0, DEFAULT_PICKER_COUNT);
  if (current && !out.includes(current)) out.push(current);
  return out;
}

// A one-line descriptor for a model name (picker subtitle).
export function modelDescriptor(model: string): string {
  const name = (model || "").split("/").pop() ?? "";
  for (const [re, text] of DESCRIPTORS) {
    if (re.test(name)) return text;
  }
  return "General-purpose model.";
}

// The short label shown on the composer control (last path segment, upper-trimmed).
export function modelShortLabel(model: string): string {
  return (model || "").split("/").pop() ?? model;
}
