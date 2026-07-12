import { describe, expect, it } from "vitest";

import { applySlash, slashSuggestions } from "./slashCommands";

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

describe("MCP prompt suggestions (P1-2)", () => {
  it("namespaced server:prompt entries match alongside skills", () => {
    const merged = [...skills, { name: "fs:summarize", description: "Summarize a file" }];
    expect(slashSuggestions(merged, "/fs:").map((s) => s.name)).toContain("fs:summarize");
    expect(slashSuggestions(merged, "/summar").map((s) => s.name)).toContain("fs:summarize");
  });
});
