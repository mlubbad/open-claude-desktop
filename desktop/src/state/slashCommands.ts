// Pure slash-command suggestion logic for the composer. When the draft begins with
// "/" and the command token isn't finished yet, suggest matching Agent Skills.

import { subsequence } from "./commandFilter";

export interface SkillInfo {
  name: string;
  description?: string;
}

// Built-in commands the BACKEND acts on, suggested alongside skills so they are
// discoverable rather than something you have to already know to type.
//
// Keep this to commands a route actually consumes. The rest of ocd_core/commands.py
// (/projects, /skills, /reload-skills, /set-instructions, /learn-finding,
// /lint-knowledge, /refresh-catalog) is legacy from the retired Chainlit client —
// nothing reads those intents here, so suggesting one would just send its literal
// text to the model.
export const BUILTIN_COMMANDS: SkillInfo[] = [
  { name: "skill-builder", description: "Build a reusable skill from this chat and save it" },
];

// Built-ins ahead of the caller's items, and a same-named item dropped. That mirrors
// the backend, which parses the command BEFORE resolve_skill — so a user skill named
// after a built-in can never run, and listing it would be a dead entry.
export function withBuiltins<T extends SkillInfo>(items: T[]): (SkillInfo | T)[] {
  const shadowed = new Set(BUILTIN_COMMANDS.map((c) => c.name));
  return [...BUILTIN_COMMANDS, ...items.filter((i) => !shadowed.has(i.name))];
}

// Skills to suggest for the current draft, or [] when the draft isn't an in-progress
// slash command. A trailing space means the command is chosen — stop suggesting so the
// user can type the skill's argument. An empty query ("/") lists everything.
export function slashSuggestions<T extends SkillInfo>(skills: T[], text: string): T[] {
  if (!text.startsWith("/")) return [];
  const rest = text.slice(1);
  if (/\s/.test(rest)) return []; // e.g. "/hero clicks" — command already committed
  const q = rest.toLowerCase();
  return skills.filter(
    (s) => subsequence(s.name.toLowerCase(), q) || subsequence((s.description ?? "").toLowerCase(), q),
  );
}

// The draft after accepting a suggestion: "/name " ready for an argument.
export function applySlash(skill: SkillInfo): string {
  return `/${skill.name} `;
}
