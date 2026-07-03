// Pure slash-command suggestion logic for the composer. When the draft begins with
// "/" and the command token isn't finished yet, suggest matching Agent Skills.

import { subsequence } from "./commandFilter";

export interface SkillInfo {
  name: string;
  description?: string;
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
