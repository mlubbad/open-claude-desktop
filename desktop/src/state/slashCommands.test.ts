import { describe, expect, it } from "vitest";

import { applySlash, BUILTIN_COMMANDS, slashSuggestions, withBuiltins } from "./slashCommands";

const skills = [
  { name: "hero", description: "Hero slide reporting" },
  { name: "summarize", description: "Condense a document" },
  { name: "chart", description: "Make a chart" },
];

describe("slashSuggestions", () => {
  it("returns [] when the draft is not a slash command", () => {
    expect(slashSuggestions(skills, "hello")).toEqual([]);
    expect(slashSuggestions(skills, "")).toEqual([]);
  });

  it("lists all skills for a bare slash", () => {
    expect(slashSuggestions(skills, "/").map((s) => s.name)).toEqual(["hero", "summarize", "chart"]);
  });

  it("filters by subsequence on name", () => {
    expect(slashSuggestions(skills, "/ch").map((s) => s.name)).toEqual(["chart"]);
    expect(slashSuggestions(skills, "/sm").map((s) => s.name)).toEqual(["summarize"]);
  });

  it("also matches the description", () => {
    expect(slashSuggestions(skills, "/report").map((s) => s.name)).toEqual(["hero"]);
  });

  it("stops suggesting once the command is committed (has a space)", () => {
    expect(slashSuggestions(skills, "/hero clicks")).toEqual([]);
  });
});

describe("applySlash", () => {
  it("produces a ready-to-argue draft", () => {
    expect(applySlash({ name: "hero" })).toBe("/hero ");
  });
});

describe("built-in commands", () => {
  it("exposes /skill-builder, which is otherwise undiscoverable (it is not a skill)", () => {
    expect(BUILTIN_COMMANDS.map((c) => c.name)).toContain("skill-builder");
    expect(BUILTIN_COMMANDS.every((c) => c.description)).toBe(true);
  });

  it("is suggested alongside skills and filters like one", () => {
    const merged = withBuiltins(skills);
    expect(slashSuggestions(merged, "/").map((s) => s.name)).toContain("skill-builder");
    expect(slashSuggestions(merged, "/skill").map((s) => s.name)).toEqual(["skill-builder"]);
    // Committed command → stop suggesting so the argument can be typed.
    expect(slashSuggestions(merged, "/skill-builder a curation report")).toEqual([]);
  });

  it("puts built-ins first and drops a skill that shadows one", () => {
    // The backend parses the command before resolve_skill, so a skill named
    // "skill-builder" can never run — listing it would be a dead entry.
    const merged = withBuiltins([...skills, { name: "skill-builder", description: "mine" }]);
    expect(merged.map((s) => s.name)).toEqual([
      "skill-builder",
      "hero",
      "summarize",
      "chart",
    ]);
    expect(merged[0].description).toBe(BUILTIN_COMMANDS[0].description);
  });

  it("leaves an unrelated skill list untouched apart from the prefix", () => {
    expect(withBuiltins(skills).slice(BUILTIN_COMMANDS.length)).toEqual(skills);
  });

  it("accepting one produces a draft ready for its argument", () => {
    expect(applySlash(BUILTIN_COMMANDS[0])).toBe("/skill-builder ");
  });

  it("lists only commands a backend route consumes", () => {
    // Legacy Chainlit intents (/projects, /skills, /reload-skills, …) are still parsed
    // by ocd_core/commands.py but no route acts on them — suggesting one would send its
    // literal text to the model.
    expect(BUILTIN_COMMANDS.map((c) => c.name)).toEqual(["skill-builder"]);
  });
});

describe("MCP prompt suggestions (P1-2)", () => {
  it("namespaced server:prompt entries match alongside skills", () => {
    const merged = [...skills, { name: "fs:summarize", description: "Summarize a file" }];
    expect(slashSuggestions(merged, "/fs:").map((s) => s.name)).toContain("fs:summarize");
    expect(slashSuggestions(merged, "/summar").map((s) => s.name)).toContain("fs:summarize");
  });
});
